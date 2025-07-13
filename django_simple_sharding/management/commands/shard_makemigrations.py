import importlib
import sys
import warnings

from django.apps import apps
from django.conf import settings
from django.core.management.base import CommandError, no_translations
from django.core.management.commands.makemigrations import (
    Command as MakeMigrationsCommand,
)
from django.db import DEFAULT_DB_ALIAS, OperationalError, connections, router
from django.db.migrations import Migration
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.questioner import (
    InteractiveMigrationQuestioner,
    NonInteractiveMigrationQuestioner,
)

from django_simple_sharding.db.migrations.autodetector import ShardMigrationAutodetector
from django_simple_sharding.db.migrations.state import ShardProjectState


class Command(MakeMigrationsCommand):
    help = "为分片模型生成迁移文件"

    def add_arguments(self, parser):
        # parser.add_argument("app_label", help="应用标签")
        parser.add_argument("--shard_keys", nargs="+", required=True, help="分片键列表")
        # parser.add_argument("--name", default=None, help="迁移文件名称")
        # parser.add_argument("--empty", action="store_true", help="创建空的迁移文件")
        super().add_arguments(parser)

    @no_translations
    def handle(self, *app_labels, **options):
        self.written_files = []
        self.shard_keys = options["shard_keys"]
        self.verbosity = options["verbosity"]
        self.interactive = options["interactive"]
        self.dry_run = options["dry_run"]
        self.merge = options["merge"]
        self.empty = options["empty"]
        self.migration_name = options["name"] or f'auto_shard_{"_".join(self.shard_keys)}'
        if self.migration_name and not self.migration_name.isidentifier():
            raise CommandError("The migration name must be a valid Python identifier.")
        self.include_header = options["include_header"]
        check_changes = options["check_changes"]
        if check_changes:
            self.dry_run = True
        self.scriptable = options["scriptable"]
        self.update = options["update"]
        # If logs and prompts are diverted to stderr, remove the ERROR style.
        if self.scriptable:
            self.stderr.style_func = None

        # Make sure the app they asked for exists
        app_labels = set(app_labels)
        has_bad_labels = False
        for app_label in app_labels:
            try:
                apps.get_app_config(app_label)
            except LookupError as err:
                self.stderr.write(str(err))
                has_bad_labels = True
        if has_bad_labels:
            sys.exit(2)

        # Load the current graph state. Pass in None for the connection so
        # the loader doesn't try to resolve replaced migrations from DB.
        loader = MigrationLoader(None, ignore_no_migrations=True)

        # Raise an error if any migrations are applied before their dependencies.
        consistency_check_labels = {config.label for config in apps.get_app_configs()}
        # Non-default databases are only checked if database routers used.
        aliases_to_check = connections if settings.DATABASE_ROUTERS else [DEFAULT_DB_ALIAS]
        for alias in sorted(aliases_to_check):
            connection = connections[alias]
            if connection.settings_dict["ENGINE"] != "django.db.backends.dummy" and any(
                # At least one model must be migrated to the database.
                router.allow_migrate(connection.alias, app_label, model_name=model._meta.object_name)
                for app_label in consistency_check_labels
                for model in apps.get_app_config(app_label).get_models()
            ):
                try:
                    loader.check_consistent_history(connection)
                except OperationalError as error:
                    warnings.warn(
                        "Got an error checking a consistent migration history "
                        "performed for database connection '%s': %s" % (alias, error),
                        RuntimeWarning,
                    )
        # Before anything else, see if there's conflicting apps and drop out
        # hard if there are any and they don't want to merge
        conflicts = loader.detect_conflicts()

        # If app_labels is specified, filter out conflicting migrations for
        # unspecified apps.
        if app_labels:
            conflicts = {app_label: conflict for app_label, conflict in conflicts.items() if app_label in app_labels}

        if conflicts and not self.merge:
            name_str = "; ".join("%s in %s" % (", ".join(names), app) for app, names in conflicts.items())
            raise CommandError(
                "Conflicting migrations detected; multiple leaf nodes in the "
                "migration graph: (%s).\nTo fix them run "
                "'python manage.py makemigrations --merge'" % name_str
            )

        for app_label in app_labels:
            self._set_app_shard_model(app_label)

        # If they want to merge and there's nothing to merge, then politely exit
        if self.merge and not conflicts:
            self.log("No conflicts detected to merge.")
            return

        # If they want to merge and there is something to merge, then
        # divert into the merge code
        if self.merge and conflicts:
            return self.handle_merge(loader, conflicts)

        if self.interactive:
            questioner = InteractiveMigrationQuestioner(
                specified_apps=app_labels,
                dry_run=self.dry_run,
                prompt_output=self.log_output,
            )
        else:
            questioner = NonInteractiveMigrationQuestioner(
                specified_apps=app_labels,
                dry_run=self.dry_run,
                verbosity=self.verbosity,
                log=self.log,
            )
        # Set up autodetector
        autodetector = ShardMigrationAutodetector(
            loader.project_state(),
            ShardProjectState.from_apps(apps),
            questioner,
        )

        # If they want to make an empty migration, make one for each app
        if self.empty:
            if not app_labels:
                raise CommandError("You must supply at least one app label when using --empty.")
            # Make a fake changes() result we can pass to arrange_for_graph
            changes = {app: [Migration("custom", app)] for app in app_labels}
            changes = autodetector.arrange_for_graph(
                changes=changes,
                graph=loader.graph,
                migration_name=self.migration_name,
            )
            self.write_migration_files(changes)
            return

        # Detect changes
        changes = autodetector.changes(
            graph=loader.graph,
            trim_to_apps=app_labels or None,
            convert_apps=app_labels or None,
            migration_name=self.migration_name,
        )

        if not changes:
            # No changes? Tell them.
            if self.verbosity >= 1:
                if app_labels:
                    if len(app_labels) == 1:
                        self.log("No changes detected in app '%s'" % app_labels.pop())
                    else:
                        self.log("No changes detected in apps '%s'" % ("', '".join(app_labels)))
                else:
                    self.log("No changes detected")
        else:
            if self.update:
                self.write_to_last_migration_files(changes)
            else:
                self.write_migration_files(changes)
            if check_changes:
                sys.exit(1)

    def _set_app_shard_model(self, app_label: str):
        # 获取应用的模型模块
        models_module = importlib.import_module(f"{app_label}.models")

        # 查找支持分片的模型
        sharding_models = []
        for attr_name in dir(models_module):
            attr = getattr(models_module, attr_name)
            if hasattr(attr, "shard") and callable(getattr(attr, "shard")):
                sharding_models.append(attr)

        if not sharding_models:
            self.stdout.write(self.style.WARNING(f"在 {app_label}.models 中没有找到支持分片的模型"))
            return

        self.stdout.write(f"找到 {len(sharding_models)} 个支持分片的模型")

        # 为每个分片键创建模型
        created_models = []
        for model in sharding_models:
            for key in self.shard_keys:
                model_name = f"{model.__name__}{key}"
                if hasattr(models_module, model_name):
                    self.stdout.write(f"模型 {model_name} 已存在，跳过")
                    continue

                # 创建分片模型
                shard_model = model.shard(key)
                created_models.append(shard_model)
                setattr(models_module, model_name, shard_model)
                self.stdout.write(f"创建分片模型: {model_name}")

        if not created_models:
            self.stdout.write(self.style.WARNING("没有创建新的分片模型"))
            return

        #
        # try:
        #     call_command(
        #         "makemigrations",
        #         self.app_label,
        #         name=migration_name,
        #         empty=self.empty,
        #         interactive=False,
        #     )
        #     self.stdout.write(self.style.SUCCESS(f"成功生成迁移文件: {migration_name}"))
        # except Exception as e:
        #     self.stdout.write(self.style.ERROR(f"生成迁移文件失败: {e}"))
        #     raise
