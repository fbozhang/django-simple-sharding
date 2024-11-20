# django-simple-sharding

## 当前实现功能

### 同库分表支持

目前，django-simple-sharding 提供了简单而高效的同库分表功能。通过继承 `ShardingModel`，开发者可以轻松地将单一的数据库表拆分成多个子表。
这种分表方式不仅有效地分担了大数据量带来的存储和查询压力，还能显著提升数据库的性能和可扩展性。

### 反向关联自动映射

在多对一关系（如外键）中，ORM 能够自动处理反向查询，使得即使在分表的情况下，反向字段依旧能够正确地映射到相应的分表中。
开发者无需编写复杂的查询逻辑，系统会自动完成对不同分表之间的关联处理，从而提升了开发效率并避免了出错的风险。

## 将要实现的功能

### 同库分区

未来，`django-simple-sharding` 将引入同库分区的功能。
在同一个数据库实例中，数据可以基于特定的逻辑（如时间范围、哈希值等）自动分配到不同的分区中。
与传统的分表策略不同，分区更多的是针对数据物理存储的划分，这不仅能优化查询性能，还能提高数据库的维护性和管理的灵活性。

### 基于自定义规则的分表

为了提供更大的灵活性，`django-simple-sharding` 将允许开发者根据自定义规则进行分表。
开发者可以根据业务需求设定数据分配策略，如基于哈希、范围等方式动态决定数据如何分布到不同的分表中。
这种方式不仅增强了分表的精准性，还能更好地应对复杂的业务场景和大规模数据的处理需求。

### 分库分表支持

在未来的版本中，`django-simple-sharding` 还将支持分库分表功能。这意味着，数据不仅可以在同一数据库实例内分布，还能跨多个数据库进行分库处理。
每个数据库内部仍然可以根据分表策略进行细粒度的数据划分。
这种跨库的分布式架构能够有效解决单库存储瓶颈、性能瓶颈以及扩展性问题，尤其适用于大规模、高并发、高可用性的分布式系统。

## 安装与配置

要在 Django 项目中开始使用分表，请按照以下步骤进行：

1. **安装包**：首先安装 `django_simple_sharding` 包。
    ```bash
    pip install django-simple-sharding
    ```
2. **更新模型**：根据需要，将模型继承自 `ShardingModel`。
3. **配置分表逻辑**：根据实际需求，您可能需要配置分表的逻辑，包括如何将记录划分到多个表或数据库中。

## 快速入门

如果您有一个普通的 Django 模型，且希望将其对应的数据库表进行分表（shard），只需要继承 `ShardingModel` 即可启用分表功能。

### 示例

假设您有一个基本的模型，且您的数据（例如：书籍数据）增长过快，您希望将数据分割到多个表中。以下是如何修改现有模型的示例：

**原始模型:**

```python
from django.db import models


class Author(models.Model):
    name = models.CharField(max_length=50)


class Book(models.Model):
    title = models.CharField(max_length=50)
    authors = models.ForeignKey(Author, related_name="books", on_delete=models.CASCADE)
```

在上面的示例中，您有两个模型：`Author` 和 `Book`。`Book` 模型通过 `ForeignKey` 关联了 `Author`。如果数据量过大，您可以将
`Book`表进行分表，将数据分布到多个数据库或表中。

**修改后的分表模型:**

```python
from django.db import models
from django_simple_sharding import models as shard_models


class Author(models.Model):
    name = models.CharField(max_length=50)


class Book(shard_models.ShardingModel):
    title = models.CharField(max_length=50)
    authors = models.ForeignKey(Author, related_name="books", on_delete=models.CASCADE)
```

### 说明

- **分表**：`Book` 模型已更新，继承了 `ShardingModel`，这使得该模型的数据可以分割到多个表或数据库中。这在处理大量数据时，能够提高性能和扩展性。
- **Author 模型**：`Author` 模型保持不变，因为它不需要进行分表。分表功能仅应用于 `Book` 模型。

通过继承 `ShardingModel`，`django_simple_sharding` 会自动将 `Book` 模型的记录分布到不同的分表（区）中。

## 关键概念

- **ShardingModel**: 这是 `django_simple_sharding` 提供的一个特殊模型，用于将单个模型拆分成多个数据库表或分区。这对于管理大量数据非常有帮助。
- **分区（Partitioning）**: 使用分表时，模型的数据会被划分到不同的分区，每个分区存储在不同的表或数据库中。分区的逻辑可以根据实际需求进行定制。

### 分表的优势

- **提升性能**：通过将数据分布到多个表或数据库中，分表可以显著提高读写性能。
- **扩展性**：分表有助于横向扩展数据库，便于管理更大的数据集。
- **更好的资源利用**：分表确保数据库系统能够高效利用资源，特别是在处理高流量应用时。

## 附加资源

- **文档**: 有关更详细的说明和高级配置选项，请查看完整文档：[django-simple-sharding 文档]()。

- **支持**: 如果您遇到任何问题，可以在 GitHub 仓库中打开 Issue。
