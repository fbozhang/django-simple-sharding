import copy
import logging
from itertools import chain
from typing import Type, TypeVar, cast

from django.apps import apps
from django.core.exceptions import (
    FieldError,
    MultipleObjectsReturned,
    ObjectDoesNotExist,
)
from django.db import connection, models
from django.db.models.base import (
    ModelBase,
    _has_contribute_to_class,
    subclass_exception,
)
from django.db.models.deletion import CASCADE
from django.db.models.fields.related import OneToOneField, resolve_relation
from django.db.models.utils import make_model_tuple

from django_simple_sharding.db.models.options import ShardingOptions

logger = logging.getLogger(__name__)
T = TypeVar("T")


class RestrictedAccessMeta(ModelBase):
    meta_options_class = ShardingOptions

    @classmethod
    def __model_base_new__(cls, name, bases, attrs, **kwargs):
        super_new = type.__new__

        # Also ensure initialization is only performed for subclasses of Model
        # (excluding Model class itself).
        parents = [b for b in bases if isinstance(b, ModelBase)]
        # parents = [b for b in bases if isinstance(b, RestrictedAccessMeta)]
        if not parents:
            return super_new(cls, name, bases, attrs)

        # Create the class.
        module = attrs.pop("__module__")
        new_attrs = {"__module__": module}
        classcell = attrs.pop("__classcell__", None)
        if classcell is not None:
            new_attrs["__classcell__"] = classcell
        attr_meta = attrs.pop("Meta", None)
        # Pass all attrs without a (Django-specific) contribute_to_class()
        # method to type.__new__() so that they're properly initialized
        # (i.e. __set_name__()).
        contributable_attrs = {}
        for obj_name, obj in attrs.items():
            if _has_contribute_to_class(obj):
                contributable_attrs[obj_name] = obj
            else:
                new_attrs[obj_name] = obj
        new_class = super_new(cls, name, bases, new_attrs, **kwargs)

        abstract = getattr(attr_meta, "abstract", False)
        meta = attr_meta or getattr(new_class, "Meta", None)
        base_meta = getattr(new_class, "_meta", None)

        app_label = None

        # Look for an application configuration to attach the model to.
        app_config = apps.get_containing_app_config(module)

        if getattr(meta, "app_label", None) is None:
            if app_config is None:
                if not abstract:
                    raise RuntimeError(
                        "Model class %s.%s doesn't declare an explicit "
                        "app_label and isn't in an application in "
                        "INSTALLED_APPS." % (module, name)
                    )

            else:
                app_label = app_config.label

        new_class.add_to_class("_meta", cls.meta_options_class(meta, app_label))
        if not abstract:
            new_class.add_to_class(
                "DoesNotExist",
                subclass_exception(
                    "DoesNotExist",
                    tuple(
                        x.DoesNotExist
                        for x in parents
                        if hasattr(x, "_meta") and not x._meta.abstract
                    )
                    or (ObjectDoesNotExist,),
                    module,
                    attached_to=new_class,
                ),
            )
            new_class.add_to_class(
                "MultipleObjectsReturned",
                subclass_exception(
                    "MultipleObjectsReturned",
                    tuple(
                        x.MultipleObjectsReturned
                        for x in parents
                        if hasattr(x, "_meta") and not x._meta.abstract
                    )
                    or (MultipleObjectsReturned,),
                    module,
                    attached_to=new_class,
                ),
            )
            if base_meta and not base_meta.abstract:
                # Non-abstract child classes inherit some attributes from their
                # non-abstract parent (unless an ABC comes before it in the
                # method resolution order).
                if not hasattr(meta, "ordering"):
                    new_class._meta.ordering = base_meta.ordering
                if not hasattr(meta, "get_latest_by"):
                    new_class._meta.get_latest_by = base_meta.get_latest_by

        is_proxy = new_class._meta.proxy

        # If the model is a proxy, ensure that the base class
        # hasn't been swapped out.
        if is_proxy and base_meta and base_meta.swapped:
            raise TypeError(
                "%s cannot proxy the swapped model '%s'." % (name, base_meta.swapped)
            )

        # Add remaining attributes (those with a contribute_to_class() method)
        # to the class.
        for obj_name, obj in contributable_attrs.items():
            new_class.add_to_class(obj_name, obj)

        # All the fields of any type declared on this model
        new_fields = chain(
            new_class._meta.local_fields,
            new_class._meta.local_many_to_many,
            new_class._meta.private_fields,
        )
        field_names = {f.name for f in new_fields}

        # Basic setup for proxy models.
        if is_proxy:
            base = None
            for parent in [kls for kls in parents if hasattr(kls, "_meta")]:
                if parent._meta.abstract:
                    if parent._meta.fields:
                        raise TypeError(
                            "Abstract base class containing model fields not "
                            "permitted for proxy model '%s'." % name
                        )
                    else:
                        continue
                if base is None:
                    base = parent
                elif parent._meta.concrete_model is not base._meta.concrete_model:
                    raise TypeError(
                        "Proxy model '%s' has more than one non-abstract model base "
                        "class." % name
                    )
            if base is None:
                raise TypeError(
                    "Proxy model '%s' has no non-abstract model base class." % name
                )
            new_class._meta.setup_proxy(base)
            new_class._meta.concrete_model = base._meta.concrete_model
        else:
            new_class._meta.concrete_model = new_class

        # Collect the parent links for multi-table inheritance.
        parent_links = {}
        for base in reversed([new_class] + parents):
            # Conceptually equivalent to `if base is Model`.
            if not hasattr(base, "_meta"):
                continue
            # Skip concrete parent classes.
            if base != new_class and not base._meta.abstract:
                continue
            # Locate OneToOneField instances.
            for field in base._meta.local_fields:
                if isinstance(field, OneToOneField) and field.remote_field.parent_link:
                    related = resolve_relation(new_class, field.remote_field.model)
                    parent_links[make_model_tuple(related)] = field

        # Track fields inherited from base models.
        inherited_attributes = set()
        # Do the appropriate setup for any model parents.
        for base in new_class.mro():
            if base not in parents or not hasattr(base, "_meta"):
                # Things without _meta aren't functional models, so they're
                # uninteresting parents.
                inherited_attributes.update(base.__dict__)
                continue

            parent_fields = base._meta.local_fields + base._meta.local_many_to_many
            if not base._meta.abstract:
                # Check for clashes between locally declared fields and those
                # on the base classes.
                for field in parent_fields:
                    if field.name in field_names:
                        raise FieldError(
                            "Local field %r in class %r clashes with field of "
                            "the same name from base class %r."
                            % (
                                field.name,
                                name,
                                base.__name__,
                            )
                        )
                    else:
                        inherited_attributes.add(field.name)

                # Concrete classes...
                base = base._meta.concrete_model
                base_key = make_model_tuple(base)
                if base_key in parent_links:
                    field = parent_links[base_key]
                elif not is_proxy:
                    attr_name = "%s_ptr" % base._meta.model_name
                    field = OneToOneField(
                        base,
                        on_delete=CASCADE,
                        name=attr_name,
                        auto_created=True,
                        parent_link=True,
                    )

                    if attr_name in field_names:
                        raise FieldError(
                            "Auto-generated field '%s' in class %r for "
                            "parent_link to base class %r clashes with "
                            "declared field of the same name."
                            % (
                                attr_name,
                                name,
                                base.__name__,
                            )
                        )

                    # Only add the ptr field if it's not already present;
                    # e.g. migrations will already have it specified
                    if not hasattr(new_class, attr_name):
                        new_class.add_to_class(attr_name, field)
                else:
                    field = None
                new_class._meta.parents[base] = field
            else:
                base_parents = base._meta.parents.copy()

                # Add fields from abstract base class if it wasn't overridden.
                for field in parent_fields:
                    if (
                        field.name not in field_names
                        and field.name not in new_class.__dict__
                        and field.name not in inherited_attributes
                    ):
                        new_field = copy.deepcopy(field)
                        new_class.add_to_class(field.name, new_field)
                        # Replace parent links defined on this base by the new
                        # field. It will be appropriately resolved if required.
                        if field.one_to_one:
                            for parent, parent_link in base_parents.items():
                                if field == parent_link:
                                    base_parents[parent] = new_field

                # Pass any non-abstract parent classes onto child.
                new_class._meta.parents.update(base_parents)

            # Inherit private fields (like GenericForeignKey) from the parent
            # class
            for field in base._meta.private_fields:
                if field.name in field_names:
                    if not base._meta.abstract:
                        raise FieldError(
                            "Local field %r in class %r clashes with field of "
                            "the same name from base class %r."
                            % (
                                field.name,
                                name,
                                base.__name__,
                            )
                        )
                else:
                    field = copy.deepcopy(field)
                    if not base._meta.abstract:
                        field.mti_inherited = True
                    new_class.add_to_class(field.name, field)

        # Copy indexes so that index names are unique when models extend an
        # abstract model.
        new_class._meta.indexes = [
            copy.deepcopy(idx) for idx in new_class._meta.indexes
        ]

        if abstract:
            # Abstract base models can't be instantiated and don't appear in
            # the list of models for an app. We do the final setup for them a
            # little differently from normal models.
            attr_meta.abstract = False
            new_class.Meta = attr_meta
            return new_class

        new_class._prepare()
        new_class._meta.apps.register_model(new_class._meta.app_label, new_class)
        return new_class

    def __new__(cls, name, bases, attrs, **kwargs):
        attr_meta = attrs.get("Meta", None)

        if cls is not OpenAccessMeta:
            if attr_meta is None:
                attr_meta = type("Meta", (), {"abstract": True})
            setattr(attr_meta, "abstract", True)
            attrs["Meta"] = attr_meta

        setattr(cls, "_super_new_done", False)
        new_cls = cls.__model_base_new__(name, bases, attrs, **kwargs)
        setattr(cls, "_super_new_done", True)

        origin_abstract = getattr(attr_meta, "abstract", False)
        setattr(new_cls, "origin_abstract", origin_abstract)
        return new_cls

    def __getattribute__(self, item):
        # print(f"RestrictedAccessMeta: {item=}")
        if item == "_super_new_done":
            return super().__getattribute__(item)
        if getattr(self, "_super_new_done", False) is False:
            return super().__getattribute__(item)
        if (
            item in ["_meta", "namespace"]
            or item.startswith("__")
            or item == "origin_abstract"
            or item == "shard"
        ):
            return super().__getattribute__(item)
        raise AttributeError(f"can't get attribute '{item}' without 'shard' ")


class OpenAccessMeta(RestrictedAccessMeta):

    def __getattribute__(self, item):
        if item == "shard" and callable(ModelBase.__getattribute__(self, "shard")):
            raise AttributeError("can't get attribute 'shard'")
        return ModelBase.__getattribute__(self, item)

    def __subclasscheck__(self, subclass):
        for base in self.mro():
            if issubclass(base, ShardingModel) and issubclass(subclass, base):
                return True

        return super().__subclasscheck__(subclass)


class ShardingModel(models.Model, metaclass=RestrictedAccessMeta):
    namespace = {}

    def __init__(self, *args, **kwargs):
        if self.origin_abstract:
            raise TypeError("Abstract models cannot be instantiated.")
        super().__init__(*args, **kwargs)

    @classmethod
    def shard(cls: Type[T], suffix: str, auto_create=False) -> T:
        if cls.origin_abstract is True:
            raise TypeError("Abstract models, can't shard.")

        app_label = cls._meta.app_label
        object_name = cls.__name__

        if suffix != "":
            object_name = f"{object_name}_{suffix}"
        model_name = f"{object_name.lower()}"
        table_name = f"{app_label}_{model_name}"

        _model = cls.namespace.get(model_name)
        if _model is not None:
            return _model

        # 动态创建一个新类，修改 db_table
        new_meta = type(
            "Meta",
            (),
            {
                "abstract": False,
                "managed": False,
                "is_shard": True,
                "db_table": table_name,
            },
        )

        # todo: 外键字段需要修改为逻辑外键
        # 创建新的类，继承原来的 cls 并设置新的 Meta
        new_cls = OpenAccessMeta(
            object_name,
            (cls,),  # 新类继承自原始的类
            {"Meta": new_meta, "__module__": cls.__module__},
        )

        if auto_create and table_name not in connection.introspection.table_names():
            with connection.schema_editor() as schema_editor:
                schema_editor.create_model(new_cls)
                logger.info(f"create table {table_name} successfully")

        #  todo: 先不拿原来的类，不然外键反向对不上。但是如果不拿原来的类会报警告重复注册
        # cls.namespace[model_name] = new_cls
        return cast(cls, new_cls)
