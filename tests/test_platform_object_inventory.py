from types import SimpleNamespace

import pytest

from server.object_store import ObjectStore
from server.platform_settings import PlatformSettings
from server.providers.base import GenerationError


def test_maintenance_inventory_paginates_only_an_exact_namespace():
    store = ObjectStore(PlatformSettings())
    def list_objects(**kwargs):
        assert kwargs['Prefix'] == 'sources/fixture-owner/'
        if 'ContinuationToken' not in kwargs:
            return {'Contents': [{'Key': 'sources/fixture-owner/a.png'}], 'IsTruncated': True, 'NextContinuationToken': 'fixture-next'}
        return {'Contents': [{'Key': 'sources/fixture-owner/b.png'}], 'IsTruncated': False}
    store._client = SimpleNamespace(list_objects_v2=list_objects)
    store.settings.s3_endpoint, store.settings.s3_bucket = 'https://fixture.test', 'fixture-bucket'
    store.settings.s3_access_key = store.settings.s3_secret_key = 'fixture-only'
    assert store.list_prefix('sources/fixture-owner/') == ['sources/fixture-owner/a.png', 'sources/fixture-owner/b.png']
    with pytest.raises(ValueError):
        store.list_prefix('sources/')


def test_out_of_scope_storage_inventory_is_rejected():
    store = ObjectStore(PlatformSettings(s3_endpoint='https://fixture.test', s3_bucket='fixture', s3_access_key='fixture', s3_secret_key='fixture'))
    store._client = SimpleNamespace(list_objects_v2=lambda **kwargs: {'Contents': [{'Key': 'sources/another-owner/private.png'}]})
    with pytest.raises(GenerationError) as failure:
        store.list_prefix('sources/fixture-owner/')
    assert failure.value.code == 'INVALID_STORAGE_INVENTORY'
