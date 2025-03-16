from django.core.signals import setting_changed
from django.db.models import Manager
from django.db.models.options import DEFAULT_NAMES as _DEFAULT_NAMES
from django.db.models.options import Options, normalize_together
from django.utils.functional import cached_property
from django.utils.text import camel_case_to_spaces, format_lazy

from django_simple_sharding.db.models.fields import SnowflakeIDField

DEFAULT_NAMES = (*_DEFAULT_NAMES, "is_shard")


class ShardingOptions(Options):
    DEFAULT_NAMES = DEFAULT_NAMES

    def contribute_to_class(self, cls, name):
        from django.db import connection
        from django.db.backends.utils import truncate_name

        cls._meta = self
        self.model = cls
        # First, construct the default values for these options.
        self.object_name = cls.__name__
        self.model_name = self.object_name.lower()
        self.verbose_name = camel_case_to_spaces(self.object_name)

        # Store the original user-defined values for each option,
        # for use when serializing the model definition
        self.original_attrs = {}

        # Next, apply any overridden values from 'class Meta'.
        if self.meta:
            meta_attrs = self.meta.__dict__.copy()
            for name in self.meta.__dict__:
                # Ignore any private attributes that Django doesn't care about.
                # NOTE: We can't modify a dictionary's contents while looping
                # over it, so we loop over the *original* dictionary instead.
                if name.startswith("_"):
                    del meta_attrs[name]
            for attr_name in self.DEFAULT_NAMES:
                if attr_name in meta_attrs:
                    setattr(self, attr_name, meta_attrs.pop(attr_name))
                    self.original_attrs[attr_name] = getattr(self, attr_name)
                elif hasattr(self.meta, attr_name):
                    setattr(self, attr_name, getattr(self.meta, attr_name))
                    self.original_attrs[attr_name] = getattr(self, attr_name)

            self.unique_together = normalize_together(self.unique_together)
            # App label/class name interpolation for names of constraints and
            # indexes.
            if not self.abstract:
                self.constraints = self._format_names(self.constraints)
                self.indexes = self._format_names(self.indexes)

            # verbose_name_plural is a special case because it uses a 's'
            # by default.
            if self.verbose_name_plural is None:
                self.verbose_name_plural = format_lazy("{}s", self.verbose_name)

            # order_with_respect_and ordering are mutually exclusive.
            self._ordering_clash = bool(self.ordering and self.order_with_respect_to)

            # Any leftover attributes must be invalid.
            if meta_attrs != {}:
                raise TypeError(
                    "'class Meta' got invalid attribute(s): %s" % ",".join(meta_attrs)
                )
        else:
            self.verbose_name_plural = format_lazy("{}s", self.verbose_name)
        del self.meta

        # If the db_table wasn't provided, use the app_label + model_name.
        if not self.db_table:
            self.db_table = "%s_%s" % (self.app_label, self.model_name)
            self.db_table = truncate_name(
                self.db_table, connection.ops.max_name_length()
            )

        if self.swappable:
            setting_changed.connect(self.setting_changed)

    def __repr__(self):
        return f"<ShardingOptions for {self.object_name}>"

    def _get_default_pk_class(self):
        return SnowflakeIDField

    @cached_property
    def base_manager(self):
        from django_simple_sharding.db.models.base import RestrictedAccessMeta

        base_manager_name = self.base_manager_name
        if not base_manager_name:
            # Get the first parent's base_manager_name if there's one.
            for parent in self.model.mro()[1:]:
                if type(parent) is not RestrictedAccessMeta and hasattr(
                    parent, "_meta"
                ):
                    if parent._base_manager.name != "_base_manager":
                        base_manager_name = parent._base_manager.name
                    break

        if base_manager_name:
            try:
                return self.managers_map[base_manager_name]
            except KeyError:
                raise ValueError(
                    f"{self.object_name} has no manager named {base_manager_name}"
                )

        manager = Manager()
        manager.name = "_base_manager"
        manager.model = self.model
        manager.auto_created = True
        return manager
