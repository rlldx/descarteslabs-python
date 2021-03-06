# Copyright 2018 Descartes Labs.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import unittest

from descarteslabs.vectors import (FeatureCollection, Feature, properties as p,
                                   WaitTimeoutError, FailedJobError, InvalidQueryException)
from descarteslabs.common.dotdict import DotDict
import mock

from .fixtures import POINT


@mock.patch('descarteslabs.vectors.featurecollection.Vector')
class TestFeatureCollection(unittest.TestCase):
    def test___init__(self, vector_client):
        id_ = 'foo'
        fc = FeatureCollection(id=id_)

        self.assertEqual(id_, fc.id)
        self.assertIsNotNone(fc.vector_client)

    def test_create(self, vector_client):
        attributes = dict(name='name',
                          title='title',
                          description='description',
                          owners=['owners'],
                          readers=['readers'],
                          writers=None)

        FeatureCollection.create(vector_client=vector_client, **attributes)

        vector_client.create_product.assert_called_once_with(
            description='description', name='name', owners=['owners'], readers=['readers'], title='title', writers=None
        )

    def test_from_jsonapi(self, vector_client):
        r = DotDict(
            id='foo',
            attributes=dict(
                owners=[], readers=[], writers=[], name='name', title='title',
                description='description'))

        fc = FeatureCollection._from_jsonapi(r)
        self.assertIsNotNone(fc.id)

        for key in r.attributes.keys():
            self.assertIsNotNone(getattr(fc, key))

    def test_filter_geometry(self, vector_client):
        vector_client.search_features = mock.Mock(return_value=iter([]))

        fc = FeatureCollection('foo', vector_client=vector_client)
        geometry = mock.MagicMock()

        filtered = fc.filter(geometry=geometry)

        self.assertEqual(fc._query_geometry, None)
        self.assertEqual(fc._query_property_expression, None)
        self.assertEqual(filtered._query_geometry, geometry)

        self.assertEqual(list(filtered.features()), [])
        vector_client.search_features.assert_called_once_with(
            geometry=geometry, query_limit=None, product_id='foo', query_expr=None
        )

    def test_filter_properties(self, vector_client):
        vector_client.search_features = mock.Mock(return_value=iter([]))

        fc = FeatureCollection('foo', vector_client=vector_client)

        exp = (p.foo > 0)
        exp2 = (p.bar >= 0)

        filtered = fc.filter(properties=exp)
        self.assertEqual(filtered._query_property_expression, exp)
        self.assertEqual(fc._query_property_expression, None)

        filtered = filtered.filter(properties=exp2)
        self.assertEqual(list(filtered.features()), [])

        vector_client.search_features.assert_called_once_with(
            geometry=None,
            query_limit=None,
            product_id='foo',
            query_expr=mock.ANY)

    def test_limit(self, vector_client):
        vector_client.search_features = mock.Mock(return_value=iter([]))

        limit = 10
        fc = FeatureCollection('foo', vector_client=vector_client).limit(limit)

        self.assertEqual(list(fc.features()), [])
        vector_client.search_features.assert_called_once_with(
            geometry=None, query_limit=10, product_id='foo', query_expr=None
        )

    def test_list(self, vector_client):
        FeatureCollection.list(vector_client=vector_client)
        vector_client.list_products.assert_called_once_with(page=1)

    def test_refresh(self, vector_client):
        attributes = dict(name='name',
                          title='title',
                          description='description',
                          owners=['owners'],
                          readers=['readers'],
                          writers=None)

        vector_client.get_product.side_effect = lambda id: DotDict(data=dict(id=id, attributes=attributes))

        fc = FeatureCollection('foo', vector_client=vector_client)
        fc.refresh()

        for key in attributes.keys():
            self.assertEqual(getattr(fc, key), attributes[key])

    def test_add_single(self, vector_client):
        vector_client = mock.MagicMock()
        fc = FeatureCollection('foo', vector_client=vector_client)

        feature = Feature(geometry=POINT, properties={})

        fc.add(feature)
        vector_client.create_features.assert_called_once_with(
            'foo', [dict(geometry=getattr(feature.geometry, '__geo_interface__', feature.geometry),
                         properties=feature.properties)]
        )

    def test_add_bulk_and_update_with_id(self, vector_client):
        def create_features(product_id, attributes):
            return DotDict(data=[dict(id=attr['properties']['id'], attributes=attr) for attr in attributes])

        vector_client.create_features.side_effect = create_features

        fc = FeatureCollection('foo', vector_client=vector_client)

        features = [
            Feature(geometry=POINT, properties=dict(id='bar')),
            Feature(geometry=POINT, properties=dict(id='bar2'))
        ]

        modified_features = fc.add(features)

        vector_client.create_features.assert_called_once_with(
            'foo', [
                dict(geometry=getattr(features[0].geometry, '__geo_interface__', features[0].geometry),
                     properties=features[0].properties),
                dict(geometry=getattr(features[1].geometry, '__geo_interface__', features[1].geometry),
                     properties=features[1].properties),
            ]
        )

        for f in modified_features:
            # the side_effect above uses properties.id instead of uuid
            self.assertEqual(f.id, f.properties.id)

    def test_delete(self, vector_client):
        fc = FeatureCollection('foo', vector_client=vector_client)

        fc.delete()
        vector_client.delete_product.assert_called_once_with('foo')

    def test_replace(self, vector_client):
        vector_client.replace.side_effect = lambda id, **attributes: {'data': dict(id=id, attributes=attributes)}

        attributes = dict(name='name',
                          title='title',
                          description='description',
                          owners=['owners'],
                          readers=['readers'],
                          writers=None)

        fc = FeatureCollection('foo', vector_client=vector_client)
        fc.replace(**attributes)

        vector_client.replace.assert_called_once_with(
            'foo', **attributes
        )

        for key in attributes.keys():
            self.assertEqual(getattr(fc, key), attributes[key])

    def test_update(self, vector_client):
        vector_client.update_product.side_effect = lambda id, **attributes: {'data': dict(id=id, attributes=attributes)}

        attributes = dict(title='title', description='description')

        fc = FeatureCollection('foo', vector_client=vector_client)
        fc.update(**attributes)

        vector_client.update_product.assert_called_once_with(
            'foo', **attributes
        )

        for key in attributes.keys():
            self.assertEqual(getattr(fc, key), attributes[key])

    def test__repr__(self, vector_client):
        fc = FeatureCollection('foo')
        self.assertEqual(repr(fc), "FeatureCollection({\n  'id': 'foo'\n})")

    def test_copy(self, vector_client):
        attributes = dict(name='name',
                          title='title',
                          description='description',
                          owners=['owners'],
                          readers=['readers'],
                          writers=None)

        fc = FeatureCollection('foo', vector_client=vector_client)
        geometry = mock.MagicMock()

        filtered = fc.filter(geometry=geometry)

        exp = (p.foo > 0)
        filtered = filtered.filter(properties=exp)

        filtered.copy(**attributes)

        vector_client.create_product_from_query.assert_called_once_with(
            description='description',
            name='name',
            owners=['owners'],
            readers=['readers'],
            title='title',
            writers=None,
            product_id="foo",
            geometry=mock.ANY,
            query_expr=mock.ANY,
            query_limit=None,
        )

    @mock.patch('descarteslabs.vectors.featurecollection.FeatureCollection.vector_client',
                new_callable=mock.PropertyMock)
    def test_wait(self, vector_client, _):
        calls = [
            DotDict({
                'data': {
                    'attributes': {
                        'created': '2019-01-03T20:07:51.720000+00:00',
                        'started': '2019-01-03T20:07:51.903000+00:00',
                        'state': 'RUNNING'
                    },
                    'id': 'c589d688-3230-4caf-9f9d-18854f71e91d',
                    'type': 'copy_query'
                }
            }),
            DotDict({
                'data': {
                    'attributes': {
                        'created': '2019-01-03T20:07:51.720000+00:00',
                        'started': '2019-01-03T20:07:51.903000+00:00',
                        'state': 'DONE'
                    },
                    'id': 'c589d688-3230-4caf-9f9d-18854f71e91d',
                    'type': 'copy_query'
                }
            })
        ]

        mock_get = mock.MagicMock(side_effect=calls)
        vector_client.return_value.get_product_from_query_status = mock_get

        FeatureCollection.COMPLETION_POLL_INTERVAL_SECONDS = 1
        FeatureCollection('foo').wait_for_copy()
        self.assertEqual(2, mock_get.call_count)

    @mock.patch('descarteslabs.vectors.featurecollection.FeatureCollection.vector_client',
                new_callable=mock.PropertyMock)
    def test_wait_failed(self, vector_client, _):
        # CopyJob.refresh called twice
        calls = [
            DotDict({
                'data': {
                    'attributes': {
                        'created': '2019-01-03T20:07:51.720000+00:00',
                        'started': '2019-01-03T20:07:51.903000+00:00',
                        'state': 'FAILURE'
                    },
                    'id': 'c589d688-3230-4caf-9f9d-18854f71e91d',
                    'type': 'copy_query'
                }
            })
        ] * 2

        mock_get = mock.MagicMock(side_effect=calls)
        vector_client.return_value.get_product_from_query_status = mock_get

        with self.assertRaises(FailedJobError):
            FeatureCollection('foo').wait_for_copy()

    @mock.patch('descarteslabs.vectors.featurecollection.FeatureCollection.vector_client',
                new_callable=mock.PropertyMock)
    def test_wait_timeout(self, vector_client, _):
        # CopyJob.refresh called thrice
        calls = [
            DotDict({
                'data': {
                    'attributes': {
                        'created': '2019-01-03T20:07:51.720000+00:00',
                        'started': '2019-01-03T20:07:51.903000+00:00',
                        'state': 'RUNNING'
                    },
                    'id': 'c589d688-3230-4caf-9f9d-18854f71e91d',
                    'type': 'copy_query'
                }
            })
        ] * 3

        mock_get = mock.MagicMock(side_effect=calls)
        vector_client.return_value.get_product_from_query_status = mock_get
        FeatureCollection.COMPLETION_POLL_INTERVAL_SECONDS = 1
        with self.assertRaises(WaitTimeoutError):
            FeatureCollection('foo').wait_for_copy(timeout=0)

    @mock.patch("descarteslabs.vectors.featurecollection.DeleteJob")
    def test_delete_features(self, vector_client, delete_job):
        fc = FeatureCollection("foo", vector_client=vector_client)

        geometry = mock.MagicMock()
        fc = fc.filter(geometry=geometry)

        exp = (p.foo > 0)
        fc = fc.filter(properties=exp)

        fc.delete_features()

        vector_client.delete_features_from_query.assert_called_once_with(product_id="foo",
                                                                         geometry=geometry,
                                                                         query_expr=exp)

    def test_delete_features_limits_fail(self, vector_client):
        fc = FeatureCollection("foo", vector_client=vector_client)
        fc = fc.limit(100)

        with self.assertRaises(InvalidQueryException):
            fc.delete_features()
