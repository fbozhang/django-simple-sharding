from django.db.models import Manager
from django.db.models.options import Options
from django.utils.functional import cached_property

from django_simple_sharding.models.fields import SnowflakeIDField


class ShardingOptions(Options):

    def __repr__(self):
        return f"<ShardingOptions for {self.object_name}>"

    def _get_default_pk_class(self):
        return SnowflakeIDField

    @cached_property
    def base_manager(self):
        from django_simple_sharding.models.base import RestrictedAccessMeta

        base_manager_name = self.base_manager_name
        if not base_manager_name:
            # Get the first parent's base_manager_name if there's one.
            for parent in self.model.mro()[1:]:
                if type(parent) is not RestrictedAccessMeta and hasattr(parent, "_meta"):
                    if parent._base_manager.name != "_base_manager":
                        base_manager_name = parent._base_manager.name
                    break

        if base_manager_name:
            try:
                return self.managers_map[base_manager_name]
            except KeyError:
                raise ValueError(f"{self.object_name} has no manager named {base_manager_name}")

        manager = Manager()
        manager.name = "_base_manager"
        manager.model = self.model
        manager.auto_created = True
        return manager
