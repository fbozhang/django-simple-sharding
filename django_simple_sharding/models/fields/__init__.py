from django.db import models

from django_simple_sharding.utils.snowflake import address_snowflake_generator


class SnowflakeIDField(models.CharField):
    def __init__(self, *args, snowflake_generator=None, **kwargs):
        kwargs.setdefault("max_length", 20)

        if snowflake_generator is None:
            snowflake_generator = address_snowflake_generator
        self._check_snowflake_generator(snowflake_generator)
        self.snowflake_generator = snowflake_generator

        super().__init__(*args, **kwargs)

    @staticmethod
    def _check_snowflake_generator(snowflake_generator):
        if not hasattr(snowflake_generator, "__next__"):
            raise ValueError(
                "The provided snowflake_generator must be an iterable object with a __next__ method."
            )

    def pre_save(self, model_instance, add):
        value = getattr(model_instance, self.attname)
        if not value:
            # generator snowflake id
            value = str(next(self.snowflake_generator))
            setattr(model_instance, self.attname, value)
        return value
