from django.db.migrations.operations.fields import (
    AddField,
    AlterField,
    FieldOperation,
    RemoveField,
    RenameField,
)
from django.db.migrations.operations.models import (
    AddConstraint,
    AddIndex,
    AlterModelManagers,
    AlterModelOptions,
    AlterOrderWithRespectTo,
    AlterTogetherOptionOperation,
    CreateModel,
    DeleteModel,
    IndexOperation,
    RemoveConstraint,
    RemoveIndex,
    RenameModel,
)

from django_simple_sharding.db.migrations.state import ShardModelState


class CreateShardModel(CreateModel):
    def state_forwards(self, app_label, state):
        state.add_model(
            ShardModelState(
                app_label,
                self.name,
                list(self.fields),
                dict(self.options),
                tuple(self.bases),
                list(self.managers),
                is_shard=True,
            )
        )

    def reduce(self, operation, app_label):
        if (
            isinstance(operation, DeleteModel)
            and self.name_lower == operation.name_lower
            and not self.options.get("proxy", False)
        ):
            return []
        elif (
            isinstance(operation, RenameModel)
            and self.name_lower == operation.old_name_lower
        ):
            return [
                # todo: 想一下要直接写CreateShardModel还是用type(self)动态决定
                type(self)(
                    operation.new_name,
                    fields=self.fields,
                    options=self.options,
                    bases=self.bases,
                    managers=self.managers,
                ),
            ]
        elif (
            isinstance(operation, AlterModelOptions)
            and self.name_lower == operation.name_lower
        ):
            options = {**self.options, **operation.options}
            for key in operation.ALTER_OPTION_KEYS:
                if key not in operation.options:
                    options.pop(key, None)
            return [
                # todo: 想一下要直接写CreateShardModel还是用type(self)动态决定
                type(self)(
                    self.name,
                    fields=self.fields,
                    options=options,
                    bases=self.bases,
                    managers=self.managers,
                ),
            ]
        elif (
            isinstance(operation, AlterModelManagers)
            and self.name_lower == operation.name_lower
        ):
            return [
                # todo: 想一下要直接写CreateShardModel还是用type(self)动态决定
                type(self)(
                    self.name,
                    fields=self.fields,
                    options=self.options,
                    bases=self.bases,
                    managers=operation.managers,
                ),
            ]
        elif (
            isinstance(operation, AlterTogetherOptionOperation)
            and self.name_lower == operation.name_lower
        ):
            return [
                # todo: 想一下要直接写CreateShardModel还是用type(self)动态决定
                type(self)(
                    self.name,
                    fields=self.fields,
                    options={
                        **self.options,
                        **{operation.option_name: operation.option_value},
                    },
                    bases=self.bases,
                    managers=self.managers,
                ),
            ]
        elif (
            isinstance(operation, AlterOrderWithRespectTo)
            and self.name_lower == operation.name_lower
        ):
            return [
                # todo: 想一下要直接写CreateShardModel还是用type(self)动态决定
                type(self)(
                    self.name,
                    fields=self.fields,
                    options={
                        **self.options,
                        "order_with_respect_to": operation.order_with_respect_to,
                    },
                    bases=self.bases,
                    managers=self.managers,
                ),
            ]
        elif (
            isinstance(operation, FieldOperation)
            and self.name_lower == operation.model_name_lower
        ):
            if isinstance(operation, AddField):
                return [
                    # todo: 想一下要直接写CreateShardModel还是用type(self)动态决定
                    type(self)(
                        self.name,
                        fields=self.fields + [(operation.name, operation.field)],
                        options=self.options,
                        bases=self.bases,
                        managers=self.managers,
                    ),
                ]
            elif isinstance(operation, AlterField):
                return [
                    # todo: 想一下要直接写CreateShardModel还是用type(self)动态决定
                    type(self)(
                        self.name,
                        fields=[
                            (n, operation.field if n == operation.name else v)
                            for n, v in self.fields
                        ],
                        options=self.options,
                        bases=self.bases,
                        managers=self.managers,
                    ),
                ]
            elif isinstance(operation, RemoveField):
                options = self.options.copy()
                for option_name in ("unique_together", "index_together"):
                    option = options.pop(option_name, None)
                    if option:
                        option = set(
                            filter(
                                bool,
                                (
                                    tuple(
                                        f for f in fields if f != operation.name_lower
                                    )
                                    for fields in option
                                ),
                            )
                        )
                        if option:
                            options[option_name] = option
                order_with_respect_to = options.get("order_with_respect_to")
                if order_with_respect_to == operation.name_lower:
                    del options["order_with_respect_to"]
                return [
                    # todo: 想一下要直接写CreateShardModel还是用type(self)动态决定
                    type(self)(
                        self.name,
                        fields=[
                            (n, v)
                            for n, v in self.fields
                            if n.lower() != operation.name_lower
                        ],
                        options=options,
                        bases=self.bases,
                        managers=self.managers,
                    ),
                ]
            elif isinstance(operation, RenameField):
                options = self.options.copy()
                for option_name in ("unique_together", "index_together"):
                    option = options.get(option_name)
                    if option:
                        options[option_name] = {
                            tuple(
                                operation.new_name if f == operation.old_name else f
                                for f in fields
                            )
                            for fields in option
                        }
                order_with_respect_to = options.get("order_with_respect_to")
                if order_with_respect_to == operation.old_name:
                    options["order_with_respect_to"] = operation.new_name
                return [
                    # todo: 想一下要直接写CreateShardModel还是用type(self)动态决定
                    type(self)(
                        self.name,
                        fields=[
                            (operation.new_name if n == operation.old_name else n, v)
                            for n, v in self.fields
                        ],
                        options=options,
                        bases=self.bases,
                        managers=self.managers,
                    ),
                ]
        elif (
            isinstance(operation, IndexOperation)
            and self.name_lower == operation.model_name_lower
        ):
            if isinstance(operation, AddIndex):
                return [
                    # todo: 想一下要直接写CreateShardModel还是用type(self)动态决定
                    type(self)(
                        self.name,
                        fields=self.fields,
                        options={
                            **self.options,
                            "indexes": [
                                *self.options.get("indexes", []),
                                operation.index,
                            ],
                        },
                        bases=self.bases,
                        managers=self.managers,
                    ),
                ]
            elif isinstance(operation, RemoveIndex):
                options_indexes = [
                    index
                    for index in self.options.get("indexes", [])
                    if index.name != operation.name
                ]
                return [
                    # todo: 想一下要直接写CreateShardModel还是用type(self)动态决定
                    type(self)(
                        self.name,
                        fields=self.fields,
                        options={
                            **self.options,
                            "indexes": options_indexes,
                        },
                        bases=self.bases,
                        managers=self.managers,
                    ),
                ]
            elif isinstance(operation, AddConstraint):
                return [
                    # todo: 想一下要直接写CreateShardModel还是用type(self)动态决定
                    type(self)(
                        self.name,
                        fields=self.fields,
                        options={
                            **self.options,
                            "constraints": [
                                *self.options.get("constraints", []),
                                operation.constraint,
                            ],
                        },
                        bases=self.bases,
                        managers=self.managers,
                    ),
                ]
            elif isinstance(operation, RemoveConstraint):
                options_constraints = [
                    constraint
                    for constraint in self.options.get("constraints", [])
                    if constraint.name != operation.name
                ]
                return [
                    # todo: 想一下要直接写CreateShardModel还是用type(self)动态决定
                    type(self)(
                        self.name,
                        fields=self.fields,
                        options={
                            **self.options,
                            "constraints": options_constraints,
                        },
                        bases=self.bases,
                        managers=self.managers,
                    ),
                ]
        return super().reduce(operation, app_label)
