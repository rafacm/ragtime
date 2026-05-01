from episodes.models import Entity


def seed_eval_entity():
    return Entity.objects.create(name="x", entity_type="person")
