from itertools import chain

from django.db.migrations import operations
from django.db.migrations.autodetector import MigrationAutodetector, OperationDependency
from django.db.migrations.utils import resolve_relation

from django_simple_sharding.db.migrations.operations.models import CreateShardModel


class ShardMigrationAutodetector(MigrationAutodetector):

    def __init__(self, from_state, to_state, questioner=None):
        super().__init__(from_state, to_state, questioner)
        # The first phase is generating all the operations for each app
        # and gathering them into a big per-app list.
        # Then go through that list, order it, and split into migrations to
        # resolve dependencies caused by M2Ms and FKs.
        self.generated_operations = {}
        self.altered_indexes = {}
        self.altered_constraints = {}
        self.renamed_fields = {}

        # Prepare some old/new state and model lists, separating
        # proxy models and ignoring unmigrated apps.
        self.old_model_keys = set()
        self.old_proxy_keys = set()
        self.old_unmanaged_keys = set()
        self.new_model_keys = set()
        self.new_proxy_keys = set()
        self.new_unmanaged_keys = set()

    def _detect_changes(self, convert_apps=None, graph=None):
        self._process_keys(convert_apps)

        self.from_state.resolve_fields_and_relations()
        self.to_state.resolve_fields_and_relations()

        # Renames have to come first
        self.generate_renamed_models()

        # Prepare lists of fields and generate through model map
        self._prepare_field_lists()
        self._generate_through_model_map()

        # Generate non-rename model operations
        self.generate_deleted_models()
        self.generate_created_models()
        self.generate_deleted_proxies()
        self.generate_created_proxies()
        self.generate_altered_options()
        self.generate_altered_managers()
        self.generate_altered_db_table_comment()

        # Create the renamed fields and store them in self.renamed_fields.
        # They are used by create_altered_indexes(), generate_altered_fields(),
        # generate_removed_altered_index/unique_together(), and
        # generate_altered_index/unique_together().
        self.create_renamed_fields()
        # Create the altered indexes and store them in self.altered_indexes.
        # This avoids the same computation in generate_removed_indexes()
        # and generate_added_indexes().
        self.create_altered_indexes()
        self.create_altered_constraints()
        # Generate index removal operations before field is removed
        self.generate_removed_constraints()
        self.generate_removed_indexes()
        # Generate field renaming operations.
        self.generate_renamed_fields()
        self.generate_renamed_indexes()
        # Generate removal of foo together.
        self.generate_removed_altered_unique_together()
        # Generate field operations.
        self.generate_removed_fields()
        self.generate_added_fields()
        self.generate_altered_fields()
        self.generate_altered_order_with_respect_to()
        self.generate_altered_unique_together()
        self.generate_added_indexes()
        self.generate_added_constraints()
        self.generate_altered_db_table()

        self._sort_migrations()
        self._build_migration_list(graph)
        self._optimize_migrations()

        return self.migrations

    @staticmethod
    def _is_shard_model(model_site):
        return getattr(model_site, "is_shard", False)

    def _process_keys(self, convert_apps=None):
        for (app_label, model_name), model_state in self.from_state.models.items():
            if not self._is_shard_model(model_state) and not model_state.options.get("managed", True):
                self.old_unmanaged_keys.add((app_label, model_name))
            elif app_label not in self.from_state.real_apps:
                if model_state.options.get("proxy"):
                    self.old_proxy_keys.add((app_label, model_name))
                else:
                    self.old_model_keys.add((app_label, model_name))

        for (app_label, model_name), model_state in self.to_state.models.items():
            if not self._is_shard_model(model_state) and not model_state.options.get("managed", True):
                self.new_unmanaged_keys.add((app_label, model_name))
            elif app_label not in self.from_state.real_apps or (
                convert_apps and app_label in convert_apps
            ):
                if model_state.options.get("proxy"):
                    self.new_proxy_keys.add((app_label, model_name))
                else:
                    self.new_model_keys.add((app_label, model_name))

    def generate_created_models(self):
        """
        Find all new models (both managed and unmanaged) and make create
        operations for them as well as separate operations to create any
        foreign key or M2M relationships (these are optimized later, if
        possible).

        Defer any model options that refer to collections of fields that might
        be deferred (e.g. unique_together).
        """
        old_keys = self.old_model_keys | self.old_unmanaged_keys
        added_models = self.new_model_keys - old_keys
        added_unmanaged_models = self.new_unmanaged_keys - old_keys
        all_added_models = chain(
            sorted(added_models, key=self.swappable_first_key, reverse=True),
            sorted(added_unmanaged_models, key=self.swappable_first_key, reverse=True),
        )
        for app_label, model_name in all_added_models:
            model_state = self.to_state.models[app_label, model_name]
            # Gather related fields
            related_fields = {}
            primary_key_rel = None
            for field_name, field in model_state.fields.items():
                if field.remote_field:
                    if field.remote_field.model:
                        if field.primary_key:
                            primary_key_rel = field.remote_field.model
                        elif not field.remote_field.parent_link:
                            related_fields[field_name] = field
                    if getattr(field.remote_field, "through", None):
                        related_fields[field_name] = field

            # Are there indexes/unique_together to defer?
            indexes = model_state.options.pop("indexes")
            constraints = model_state.options.pop("constraints")
            unique_together = model_state.options.pop("unique_together", None)
            order_with_respect_to = model_state.options.pop(
                "order_with_respect_to", None
            )
            # Depend on the deletion of any possible proxy version of us
            dependencies = [
                OperationDependency(
                    app_label, model_name, None, OperationDependency.Type.REMOVE
                ),
            ]
            # Depend on all bases
            for base in model_state.bases:
                if isinstance(base, str) and "." in base:
                    base_app_label, base_name = base.split(".", 1)
                    dependencies.append(
                        OperationDependency(
                            base_app_label,
                            base_name,
                            None,
                            OperationDependency.Type.CREATE,
                        )
                    )
                    # Depend on the removal of base fields if the new model has
                    # a field with the same name.
                    old_base_model_state = self.from_state.models.get(
                        (base_app_label, base_name)
                    )
                    new_base_model_state = self.to_state.models.get(
                        (base_app_label, base_name)
                    )
                    if old_base_model_state and new_base_model_state:
                        removed_base_fields = (
                            set(old_base_model_state.fields)
                            .difference(
                                new_base_model_state.fields,
                            )
                            .intersection(model_state.fields)
                        )
                        for removed_base_field in removed_base_fields:
                            dependencies.append(
                                OperationDependency(
                                    base_app_label,
                                    base_name,
                                    removed_base_field,
                                    OperationDependency.Type.REMOVE,
                                )
                            )
            # Depend on the other end of the primary key if it's a relation
            if primary_key_rel:
                dependencies.append(
                    OperationDependency(
                        *resolve_relation(primary_key_rel, app_label, model_name),
                        None,
                        OperationDependency.Type.CREATE,
                    ),
                )
            # Generate creation operation
            create_model_class = operations.CreateModel
            if self._is_shard_model(model_state):
                create_model_class = CreateShardModel
            self.add_operation(
                app_label,
                create_model_class(
                    name=model_state.name,
                    fields=[
                        d
                        for d in model_state.fields.items()
                        if d[0] not in related_fields
                    ],
                    options=model_state.options,
                    bases=model_state.bases,
                    managers=model_state.managers,
                ),
                dependencies=dependencies,
                beginning=True,
            )

            # Don't add operations which modify the database for unmanaged models
            if not self._is_shard_model(model_state) and not model_state.options.get("managed", True):
                continue

            # Generate operations for each related field
            for name, field in sorted(related_fields.items()):
                dependencies = self._get_dependencies_for_foreign_key(
                    app_label,
                    model_name,
                    field,
                    self.to_state,
                )
                # Depend on our own model being created
                dependencies.append(
                    OperationDependency(
                        app_label, model_name, None, OperationDependency.Type.CREATE
                    )
                )
                # Make operation
                self.add_operation(
                    app_label,
                    operations.AddField(
                        model_name=model_name,
                        name=name,
                        field=field,
                    ),
                    dependencies=list(set(dependencies)),
                )
            # Generate other opns
            if order_with_respect_to:
                self.add_operation(
                    app_label,
                    operations.AlterOrderWithRespectTo(
                        name=model_name,
                        order_with_respect_to=order_with_respect_to,
                    ),
                    dependencies=[
                        OperationDependency(
                            app_label,
                            model_name,
                            order_with_respect_to,
                            OperationDependency.Type.CREATE,
                        ),
                        OperationDependency(
                            app_label, model_name, None, OperationDependency.Type.CREATE
                        ),
                    ],
                )
            related_dependencies = [
                OperationDependency(
                    app_label, model_name, name, OperationDependency.Type.CREATE
                )
                for name in sorted(related_fields)
            ]
            related_dependencies.append(
                OperationDependency(
                    app_label, model_name, None, OperationDependency.Type.CREATE
                )
            )
            for index in indexes:
                self.add_operation(
                    app_label,
                    operations.AddIndex(
                        model_name=model_name,
                        index=index,
                    ),
                    dependencies=related_dependencies,
                )
            for constraint in constraints:
                self.add_operation(
                    app_label,
                    operations.AddConstraint(
                        model_name=model_name,
                        constraint=constraint,
                    ),
                    dependencies=related_dependencies,
                )
            if unique_together:
                self.add_operation(
                    app_label,
                    operations.AlterUniqueTogether(
                        name=model_name,
                        unique_together=unique_together,
                    ),
                    dependencies=related_dependencies,
                )
            # Fix relationships if the model changed from a proxy model to a
            # concrete model.
            relations = self.to_state.relations
            if (app_label, model_name) in self.old_proxy_keys:
                for related_model_key, related_fields in relations[
                    app_label, model_name
                ].items():
                    related_model_state = self.to_state.models[related_model_key]
                    for related_field_name, related_field in related_fields.items():
                        self.add_operation(
                            related_model_state.app_label,
                            operations.AlterField(
                                model_name=related_model_state.name,
                                name=related_field_name,
                                field=related_field,
                            ),
                            dependencies=[
                                OperationDependency(
                                    app_label,
                                    model_name,
                                    None,
                                    OperationDependency.Type.CREATE,
                                )
                            ],
                        )
