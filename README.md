# django-simple-sharding

## Current Features

### Same Database Table Sharding

Currently, `django-simple-sharding` provides an easy and efficient way to implement sharding within a single database.
By
inheriting from `ShardingModel`, developers can effortlessly split a large database table into multiple smaller
partitions (shards). This approach alleviates the storage and query load caused by large datasets, while significantly
enhancing database performance and scalability.

### Automatic Reverse Foreign Key Handling

In the case of many-to-one relationships (such as foreign keys), the ORM automatically resolves reverse queries to the
correct shard, even when data is distributed across multiple partitions. Developers do not need to manually adjust
queries to account for sharded tables, as the system handles the mapping between related records and their respective
shards, greatly improving development efficiency and reducing the potential for errors.

## Planned Features

### Same Database Partitioning

In future releases, `django-simple-sharding` will introduce same-database partitioning. Data within a single database
instance can be automatically partitioned based on specific logic, such as time ranges or hash values. Unlike
traditional sharding, partitioning focuses on the physical distribution of data, which not only improves query
performance but also offers greater flexibility in database management and maintenance.

### Customizable Sharding Rules

To provide greater flexibility, `django-simple-sharding` will allow developers to define their own sharding rules.
Developers will be able to dynamically determine how data should be distributed across different shards based on custom
business logic, such as hash-based or range-based strategies. This feature will enhance the precision of data
distribution and make it easier to manage complex business requirements and large-scale datasets.

### Cross-Database Sharding

In upcoming versions, `django-simple-sharding` will support cross-database sharding. This feature enables data to be
distributed across multiple database instances, and within each database, data can still be partitioned into multiple
tables. This distributed architecture addresses the challenges of scalability, performance bottlenecks, and storage
limitations in a single database. It is particularly beneficial for large-scale, high-traffic, and high-availability
systems that require horizontal scaling across multiple database clusters.

## Setup

To get started with sharding in your Django project, follow these steps:

1. **Install the Package**: First, install the `django_simple_sharding` package.
    ```bash
    pip install django-simple-sharding
    ```
2. **Update Your Models**: Modify your models to inherit from `ShardingModel` where necessary.
3. **Configure Sharding**: Depending on your use case, you may need to configure the sharding logic, including
   specifying
   how records should be partitioned across multiple tables or databases.

## Quick Start Guide

If you have a standard Django model and wish to shard (split) its corresponding database table, simply inherit from
`ShardingModel` to enable sharding functionality.

### example

Suppose you have a basic model setup, and your data (e.g., books) is growing too large, making it necessary to split the
data across multiple tables. Here's how you can modify your existing model:

**Original Model:**

```python
from django.db import models


class Author(models.Model):
    name = models.CharField(max_length=50)


class Book(models.Model):
    title = models.CharField(max_length=50)
    authors = models.ForeignKey(Author, related_name="books", on_delete=models.CASCADE)
```

In the example above, you have two models: `Author` and `Book`. The `Book` model has a `ForeignKey` to `Author`.
If your data grows too large, you can shard the `Book` table to distribute the data across multiple databases or tables.

**Modified Model for Sharding:**

```python
from django.db import models
from django_simple_sharding import models as shard_models


class Author(models.Model):
    name = models.CharField(max_length=50)


class Book(shard_models.ShardingModel):
    title = models.CharField(max_length=50)
    authors = models.ForeignKey(Author, related_name="books", on_delete=models.CASCADE)
```

### Explanation

- **Sharding**: The `Book` model has been updated to inherit from `ShardingModel`. This enables the model to be sharded
  across multiple tables or databases, which can improve performance and scalability when dealing with large datasets.
- **Author Model**: The `Author` model remains unchanged, as it does not need to be sharded. Sharding is applied only to
  the `Book` model.

By inheriting from `ShardingModel`, Django Simple Sharding automatically handles the distribution of records across
different tables (partitions) for the `Book` model.

## Key Concepts

- **ShardingModel**: This is a special model provided by the `django_simple_sharding` package. It is used to split a
  single model into multiple database tables or partitions. This can help in managing large datasets more effectively.
- **Partitioning**: When using sharding, the data for a model is divided into different partitions, each stored in a
  separate table or database. The partitioning logic can be customized based on your requirements.

### Benefits of Sharding

- **Improved Performance**: By distributing data across multiple tables or databases, sharding can significantly improve
  read and write performance.
- **Scalability**: Sharding helps scale the database horizontally, making it easier to manage larger datasets.
- **Better Resource Utilization**: Sharding ensures that the database system can efficiently utilize its resources,
  especially when dealing with high-traffic applications.

## Additional Resources

- **Documentation**: For more detailed instructions and advanced configuration options, check out the full documentation
  at [django-simple-sharding documentation]().

- **Support**: If you encounter any issues, feel free to open an issue on the GitHub repository.
