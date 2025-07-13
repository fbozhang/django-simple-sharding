from django.db.migrations.state import ModelState, ProjectState

from django_simple_sharding.db.models import ShardingModel


class ShardProjectState(ProjectState):

    @classmethod
    def from_apps(cls, apps):
        """Take an Apps and return a ProjectState matching it."""
        app_models = {}
        for model in apps.get_models(include_swapped=True):
            model_state = ShardModelState.from_model(model)
            app_models[(model_state.app_label, model_state.name_lower)] = model_state
        return cls(app_models)


class ShardModelState(ModelState):

    def __init__(
        self,
        app_label,
        name,
        fields,
        options=None,
        bases=None,
        managers=None,
        is_shard=False,
    ):
        super().__init__(app_label, name, fields, options, bases, managers)
        self.is_shard = is_shard
        # for base in self.bases:
        #     if issubclass(base, ShardingModel):
        #         # todo: 细想一下要加在meta option然后再重写迁移命令迁移时忽略这个参数还是在model state添加bases属性为shardmodel的子类
        #         self.is_shard = True
        #         break

    @classmethod
    def from_model(cls, model, exclude_rels=False):
        """Given a model, return a ModelState representing it."""
        state = super().from_model(model, exclude_rels=exclude_rels)
        if issubclass(model, ShardingModel):
            state.is_shard = True
            # todo: 想一下要不要把bases添加ShardingModel
        return state
