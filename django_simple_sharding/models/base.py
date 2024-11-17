import copy
import logging

from django.db import models, connection
from django.db.models.base import ModelBase

logger = logging.getLogger(__name__)


class RestrictedAccessMeta(ModelBase):

    def __new__(cls, name, bases, attrs, **kwargs):

        # Also ensure initialization is only performed for subclasses of ShardingModel
        # (excluding ShardingModel class itself).
        # parents = [b for b in bases if isinstance(b, RestrictedAccessMeta)]
        # if not parents:
        #     return type.__new__(cls,name, bases, attrs)

        attr_meta = attrs.get("Meta", None)

        if cls is not OpenAccessMeta:
            if attr_meta is None:
                attr_meta = type("Meta", (), {"abstract": True})
            setattr(attr_meta, "abstract", True)
            attrs["Meta"] = attr_meta

        setattr(cls, "_super_new_done", False)
        new_cls = super().__new__(cls, name, bases, attrs, **kwargs)
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
        return ModelBase.__getattribute__(self, item)


class ShardingModel(models.Model, metaclass=RestrictedAccessMeta):
    namespace = {}

    def __init__(self, *args, **kwargs):
        if self.origin_abstract:
            raise TypeError("Abstract models cannot be instantiated.")
        super().__init__(*args, **kwargs)

    @classmethod
    def shard(cls, suffix, auto_create=False):
        if cls.origin_abstract is True:
            raise TypeError("Abstract models, can't shard.")

        app_label = cls._meta.app_label
        model_name = f"{cls.__name__.lower()}"
        if suffix != "":
            model_name = f"{model_name}_{suffix}"

        table_name = f"{app_label}_{model_name}"
        if not auto_create and table_name not in connection.introspection.table_names():
            raise ValueError(f"Can't find table name {table_name}")

        _model = cls.namespace.get(model_name)
        if _model is not None:
            return _model

        from django.db.models import options

        # 添加一个Meta属性
        # todo: 考虑下有没有意义
        _origin_default_names = options.DEFAULT_NAMES
        _new_default_names = copy.copy(_origin_default_names) + ("model_name",)
        options.DEFAULT_NAMES = _new_default_names

        meta_attrs = cls._meta.__dict__.copy()
        _old_meta_attrs = {
            attr_name: meta_attrs.pop(attr_name)
            for attr_name in options.DEFAULT_NAMES
            if attr_name in meta_attrs
        }
        # 动态创建一个新类，修改 db_table
        new_meta = type(
            "Meta",
            (),
            {
                **_old_meta_attrs,
                "abstract": False,
                "db_table": table_name,
                "managed": False,
                "model_name": model_name,
            },
        )

        # 创建新的类，继承原来的 cls 并设置新的 Meta
        new_cls = OpenAccessMeta(
            cls.__name__,
            (cls,),  # 新类继承自原始的类
            {"Meta": new_meta, "__module__": cls.__module__},
        )

        options.DEFAULT_NAMES = _origin_default_names

        if auto_create and table_name not in connection.introspection.table_names():
            with connection.schema_editor() as schema_editor:
                schema_editor.create_model(new_cls)
                logger.info(f"create table {table_name} successfully")

        #  todo: 先不拿原来的类，不然外键反向对不上。但是如果不拿原来的类会报警告重复注册
        # cls.namespace[model_name] = new_cls
        return new_cls
