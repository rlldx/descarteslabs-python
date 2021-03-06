import copy

from descarteslabs.common.dotdict import DotDict
from descarteslabs.client.exceptions import NotFoundError
from descarteslabs.common.tasks import UploadTask
from descarteslabs.client.services.vector import Vector
from descarteslabs.vectors.feature import Feature

# import these exceptions for backwards compatibility
from descarteslabs.vectors.exceptions import (InvalidQueryException,   # noqa
    VectorException, FailedCopyError, WaitTimeoutError)
from descarteslabs.vectors.async_job import DeleteJob, CopyJob
import six


class _FeaturesIterator(object):
    """Private iterator for features() that also returns length"""

    def __init__(self, response):
        self._response = response

    def __len__(self):
        return len(self._response)

    def __iter__(self):
        return self

    def __next__(self):
        return Feature._create_from_jsonapi(next(self._response))

    def next(self):
        """Backwards compatibility for Python 2"""
        return self.__next__()


class FeatureCollection(object):
    """
    A proxy object for accesssing millions of features within a collection
    having similar access controls, geometries and properties.  Such a
    grouping is named a ``product`` and identified by ``id``.

    If creating a new `FeatureCollection` use `FeatureCollection.create()`
    instead.

    Features will not be retrieved from the `FeatureCollection` until
    `FeatureCollection.features()` is called.

    Attributes
    ----------
    id : str
        The unique identifier for this `FeatureCollection`.
    name : str
        A short name without spaces (like a handle).
    title : str
        A more verbose and expressive name for display purposes.
    description : str
        Information about the `FeatureCollection`, why it exists,
        and what it provides.
    owners : list(str)
        User, group, or organization IDs that own
        this FeatureCollection.  Defaults to
        [``user:current_user``, ``org:current_org``].
        The owner can edit, delete, and change access to
        this `FeatureCollection`.
    readers : list(str)
        User, group, or organization IDs that can read
        this `FeatureCollection`.
    writers : list(str)
        User, group, or organization IDs that can edit
        this `FeatureCollection` (includes read permission).

    Note
    ----
    All ``owner``, ``reader``, and ``writer`` IDs must be prefixed with
    ``email:``, ``user:``, ``group:`` or ``org:``.  Using ``org:`` as an
    ``owner`` will assign those privileges only to administrators for
    that organization; using ``org:`` as a ``reader`` or ``writer``
    assigns those privileges to everyone in that organization.
    """

    ATTRIBUTES = ['owners', 'writers', 'readers', 'id', 'name', 'title', 'description']
    COMPLETE_STATUSES = ["DONE", "SUCCESS", "FAILURE"]
    COMPLETION_POLL_INTERVAL_SECONDS = 5

    def __init__(self, id=None, vector_client=None):

        self.id = id
        self._vector_client = vector_client

        self._query_geometry = None
        self._query_limit = None
        self._query_property_expression = None

        self.refresh()

    @classmethod
    def _from_jsonapi(cls, response, vector_client=None):
        self = cls(response.id, vector_client=vector_client)
        self.__dict__.update(response.attributes)

        return self

    @classmethod
    def create(cls, name, title, description, owners=None, readers=None, writers=None, vector_client=None):
        """
        Create a vector product in your catalog.

        Parameters
        ----------
        name : str
            A short name without spaces (like a handle).
        title : str
            A more verbose and expressive name for display purposes.
        description : str
            Information about the `FeatureCollection`, why it exists,
            and what it provides.
        owners : list(str), optional
            User, group, or organization IDs that own
            the newly created FeatureCollection.  Defaults to
            [``current user``, ``current org``].
            The owner can edit and delete this `FeatureCollection`.
        readers : list(str), optional
            User, group, or organization IDs that can read
            the newly created `FeatureCollection`.
        writers : list(str), optional
            User, group, or organization IDs that can edit
            the newly created `FeatureCollection` (includes read permission).

        Example
        -------
        >>> from descarteslabs.vectors import FeatureCollection
        >>> FeatureCollection.create(name='foo',
        ...    title='My Foo Vector Collection',
        ...    description='Just a test')  # doctest: +SKIP
        """
        params = dict(
            name=name,
            title=title,
            description=description,
            owners=owners,
            readers=readers,
            writers=writers,
        )

        if vector_client is None:
            vector_client = Vector()

        return cls._from_jsonapi(vector_client.create_product(**params).data, vector_client)

    @classmethod
    def list(cls, vector_client=None):
        """
        List all `FeatureCollection` products that you have access to.

        Returns
        -------
        list(`FeatureCollection`)
            A list of all products that you have access to.

        Example
        -------
        >>> from descarteslabs.vectors import FeatureCollection
        >>> FeatureCollection.list()  # doctest: +SKIP
        """

        if vector_client is None:
            vector_client = Vector()

        list = []

        page = 1
        # The first page will always succeed...
        response = vector_client.list_products(page=page)

        while len(response) > 0:
            partial_list = [cls._from_jsonapi(fc, vector_client)
                            for fc in response.data]
            list.extend(partial_list)
            page += 1

            # Subsequent pages may throw NotFoundError
            try:
                response = vector_client.list_products(page=page)
            except NotFoundError:
                response = []

        return list

    @property
    def vector_client(self):
        if self._vector_client is None:
            self._vector_client = Vector()
        return self._vector_client

    def filter(self, geometry=None, properties=None):
        """
        Include only the features matching the given geometry and properties.
        Filters are not evaluated until iterating over the FeatureCollection,
        and can be chained by calling filter multiple times.

        Parameters
        ----------
        geometry: GeoJSON-like dict, object with ``__geo_interface__``; optional
            Include features intersecting this geometry. If this
            FeatureCollection is already filtered by a geometry,
            the new geometry will override it -- they cannot be chained.
        properties : descarteslabs.common.property_filtering.Expression
            Include features having properties where the expression
            evaluates as ``True``
            E.g ``properties=(p.temperature >= 50) & (p.hour_of_day > 18)``,
            or even more complicated expressions like
            ``properties=(100 > p.temperature >= 50) | ((p.month != 10) & (p.day_of_month > 14))``
            If you supply a property which doesn't exist as part of the
            expression that comparison will evaluate to False.

        Returns
        -------
        vectors.FeatureCollection
            A new `FeatureCollection` with the given filter.

        Example
        -------
        >>> from descarteslabs.vectors import FeatureCollection, properties as p
        >>> aoi_geometry = {
        ...    'type': 'Polygon',
        ...    'coordinates': [[[-109, 31], [-102, 31], [-102, 37], [-109, 37], [-109, 31]]]}
        >>> all_us_cities = FeatureCollection('d1349cc2d8854d998aa6da92dc2bd24')  # doctest: +SKIP
        >>> filtered_cities = all_us_cities.filter(properties=(p.name.like("S%")))  # doctest: +SKIP
        >>> filtered_cities = filtered_cities.filter(geometry=aoi_geometry)  # doctest: +SKIP
        >>> filtered_cities = filtered_cities.filter(properties=(p.area_land_meters > 1000))  # doctest: +SKIP

        """
        copied_fc = copy.deepcopy(self)

        if geometry is not None:
            copied_fc._query_geometry = getattr(geometry, '__geo_interface__', geometry)

        if properties is not None:
            if copied_fc._query_property_expression is None:
                copied_fc._query_property_expression = properties
            else:
                copied_fc._query_property_expression = copied_fc._query_property_expression & properties

        return copied_fc

    def limit(self, limit):
        """
        Limit the number of `Feature` yielded in `FeatureCollection.features()`.

        Parameters
        ----------
        limit : int
            The number of rows to limit the result to.

        Returns
        -------
        vectors.FeatureCollection
            A new `FeatureCollection` with the given limit.

        Example
        -------
        >>> from descarteslabs.vectors import FeatureCollection
        >>> fc = FeatureCollection('d1349cc2d8854d998aa6da92dc2bd24')  # doctest: +SKIP
        >>> fc = fc.limit(10)  # doctest: +SKIP

        """
        copied_fc = copy.deepcopy(self)
        copied_fc._query_limit = limit
        return copied_fc

    def features(self):
        """
        Iterate through each `Feature` in the `FeatureCollection`, taking into
        account calls to `FeatureCollection.filter()` and
        `FeatureCollection.limit()`.

        A query or limit of some sort must be set, otherwise a BadRequestError
        will be raised.

        The length of the returned iterator indicates the full query size.

        Returns
        -------
        `Iterator` which returns `Feature` and has a length

        Example
        -------
        >>> from descarteslabs.vectors import FeatureCollection
        >>> fc = FeatureCollection('d1349cc2d8854d998aa6da92dc2bd24')  # doctest: +SKIP
        >>> features = fc.features()  #doctest: +SKIP
        >>> print(len(features))  #doctest: +SKIP
        >>> for feature in features:  # doctest: +SKIP
        ...    print(feature)  # doctest: +SKIP
        """
        params = dict(
            product_id=self.id,
            geometry=self._query_geometry,
            query_expr=self._query_property_expression,
            query_limit=self._query_limit,
        )

        return _FeaturesIterator(self.vector_client.search_features(**params))

    def update(self,
               name=None,
               title=None,
               description=None,
               owners=None,
               readers=None,
               writers=None):
        """
        Updates the attributes of the `FeatureCollection`.

        Parameters
        ----------
        name : str, optional
            A short name without spaces (like a handle).
        title : str, optional
            A more verbose and expressive name for display purposes.
        description : str, optional
            Information about the `FeatureCollection`, why it exists,
            and what it provides.
        owners : list(str), optional
            User, group, or organization IDs that own
            the FeatureCollection.  Defaults to
            [``current user``, ``current org``].
            The owner can edit and delete this `FeatureCollection`.
        readers : list(str), optional
            User, group, or organization IDs that can read
            the `FeatureCollection`.
        writers : list(str), optional
            User, group, or organization IDs that can edit
            the `FeatureCollection` (includes read permission).

        Example
        -------
        >>> attributes = dict(name='name',
        ...    owners=['email:me@org.com'],
        ...    readers=['group:trusted'])
        >>> FeatureCollection('d1349cc2d8854d998aa6da92dc2bd24').update(**attributes)  # doctest: +SKIP

        """
        params = dict(
            name=name,
            title=title,
            description=description,
            owners=owners,
            readers=readers,
            writers=writers,
        )

        params = {k: v for k, v in six.iteritems(params) if v is not None}

        response = self.vector_client.update_product(self.id, **params)
        self.__dict__.update(response['data']['attributes'])

    def replace(
            self,
            name,
            title,
            description,
            owners=None,
            readers=None,
            writers=None,
    ):
        """
        Replaces the attributes of the `FeatureCollection`.

        To change a single attribute, see `FeatureCollection.update()`.

        Parameters
        ----------
        name : str
            A short name without spaces (like a handle).
        title : str
            A more verbose name for display purposes.
        description : str
            Information about the `FeatureCollection`, why it exists,
            and what it provides.
        owners : list(str), optional
            User, group, or organization IDs that own
            the FeatureCollection.  Defaults to
            [``current user``, ``current org``].
            The owner can edit and delete this `FeatureCollection`.
        readers : list(str), optional
            User, group, or organization IDs that can read
            the `FeatureCollection`.
        writers : list(str), optional
            User, group, or organization IDs that can edit
            the `FeatureCollection` (includes read permission).

        Example
        -------
        >>> attributes = dict(name='name',
        ...    title='title',
        ...    description='description',
        ...    owners=['email:you@org.com'],
        ...    readers=['group:readers'],
        ...    writers=[])
        >>> FeatureCollection('foo').replace(**attributes)  # doctest: +SKIP
        """

        params = dict(
            name=name,
            title=title,
            description=description,
            owners=owners,
            readers=readers,
            writers=writers,
        )

        response = self.vector_client.replace(self.id, **params)
        self.__dict__.update(response['data']['attributes'])

    def refresh(self):
        """
        Loads the attributes for the `FeatureCollection`.

        """
        response = self.vector_client.get_product(self.id)
        self.__dict__.update(response.data.attributes)

    def delete(self):
        """
        Delete the `FeatureCollection` from the catalog.

        Example
        -------
        >>> from descarteslabs.vectors import FeatureCollection
        >>> FeatureCollection('foo').delete()  # doctest: +SKIP

        """

        self.vector_client.delete_product(self.id)

    def add(self, features):
        """
        Add multiple features to an existing `FeatureCollection`.

        Parameters
        ----------
        features : `Feature` or list(`Feature`)
            A single feature or list of features to add. Collections
            of more than 100 features will be batched in groups of 100,
            but consider using upload() instead.

        Returns
        -------
        list(`Feature`)
            A copy of the given list of features that includes the ``id``.

        Example
        -------
        >>> from descarteslabs.vectors import FeatureCollection, Feature
        >>> polygon = {
        ...    'type': 'Polygon',
        ...    'coordinates': [[[-95, 42],[-93, 42],[-93, 40],[-95, 41],[-95, 42]]]}
        >>> features = [Feature(geometry=polygon, properties={}) for _ in range(100)]
        >>> FeatureCollection('foo').add(features)  # doctest: +SKIP

        """
        if isinstance(features, Feature):
            features = [features]

        attributes = [{k: v for k, v in f.geojson.items() if k in ['properties', 'geometry']} for f in features]

        documents = self.vector_client.create_features(self.id, attributes)

        copied_features = copy.deepcopy(features)

        for feature, doc in zip(copied_features, documents.data):
            feature.id = doc.id

        return copied_features

    def upload(self, file_ref, max_errors=0):
        """
        Asynchonously add features from a file of
        `Newline Delimited JSON <https://github.com/ndjson/ndjson-spec>`_
        features.  The file itself will be uploaded synchronously,
        but loading the features is done asynchronously.

        Parameters
        ----------
        file_ref : io.IOBase or str
            An open file object, or a path to the file to upload.
        max_errors : int
            The maximum number of errors permitted before declaring failure.

        Returns
        -------
        `UploadTask`
            The upload task.  The details may take time to become available
            so asking for them before they're available will block
            until the details are available.
        """
        upload_id = self.vector_client.upload_features(file_ref, self.id)
        return UploadTask(self.id, upload_id=upload_id,
                          client=self.vector_client)

    def list_uploads(self):
        """
        Get all the upload tasks for this product.

        Returns
        -------
        list(`UploadTask`)
            The list of tasks for the product.
        """
        results = []

        for result in self.vector_client.get_upload_results(self.id):
            results.append(UploadTask(self.id, tuid=result.id,
                                      result_attrs=result.attributes,
                                      client=self.vector_client))

        return results

    def copy(self, name, title, description, owners=None, readers=None, writers=None):
        """
        Apply a filter to an existing product and create a new vector product in your catalog
        from the result, taking into account calls to `FeatureCollection.filter()`
        and `FeatureCollection.limit()`.

        A query of some sort must be set, otherwise a BadRequestError will be raised.

        Copies occur asynchronously and can take a long time to complete.  Features
        will not be accessible in the new FeatureCollection until the copy completes.  Use
        `FeatureCollection.wait_for_copy()` to block until the copy completes.

        Parameters
        ----------
        name : str
            A short name without spaces (like a handle).
        title : str
            A more verbose and expressive name for display purposes.
        description : str
            Information about the `FeatureCollection`, why it exists,
            and what it provides.
        owners : list(str), optional
            User, group, or organization IDs that own
            the newly created FeatureCollection.  Defaults to
            [``current user``, ``current org``].
            The owner can edit and delete this `FeatureCollection`.
        readers : list(str), optional
            User, group, or organization IDs that can read
            the newly created `FeatureCollection`.
        writers : list(str), optional
            User, group, or organization IDs that can edit
            the newly created `FeatureCollection` (includes read permission).

        Returns
        -------
        vectors.FeatureCollection
            A new `FeatureCollection`.

        Example
        -------
        >>> from descarteslabs.vectors import FeatureCollection, properties as p
        >>> aoi_geometry = {
        ...    'type': 'Polygon',
        ...    'coordinates': [[[-109, 31], [-102, 31], [-102, 37], [-109, 37], [-109, 31]]]}
        >>> all_us_cities = FeatureCollection('d1349cc2d8854d998aa6da92dc2bd24')  # doctest: +SKIP
        >>> filtered_cities = all_us_cities.filter(properties=(p.name.like("S%")))  # doctest: +SKIP
        >>> filtered_cities = filtered_cities.filter(geometry=aoi_geometry)  # doctest: +SKIP
        >>> filtered_cities = filtered_cities.filter(properties=(p.area_land_meters > 1000))  # doctest: +SKIP
        >>> filtered_cities_fc = filtered_cities.copy(name='filtered-cities',
        ...    title='My Filtered US Cities Vector Collection',
        ...    description='A collection of cities in the US')  # doctest: +SKIP
        """
        params = dict(
            product_id=self.id,
            geometry=self._query_geometry,
            query_expr=self._query_property_expression,
            query_limit=self._query_limit,
            name=name,
            title=title,
            description=description,
            owners=owners,
            readers=readers,
            writers=writers,
        )

        return self._from_jsonapi(self.vector_client.create_product_from_query(**params).data)

    def wait_for_copy(self, timeout=None):
        """
        Wait for a copy operation to complete. Copies occur asynchronously
        and can take a long time to complete.  Features will not be accessible
        in the FeatureCollection until the copy completes.

        If the product was not created using a copy job, a BadRequestError is raised.
        If the copy job ran, but failed, a FailedJobError is raised.
        If a timeout is specified and the timeout is reached, a WaitTimeoutError is raised.

        Parameters
        ----------
        timeout : int
            Number of seconds to wait before the wait times out.  If not specified, will
            wait indefinitely.

        Example
        -------
        >>> from descarteslabs.vectors import FeatureCollection, properties as p
        >>> aoi_geometry = {
        ...    'type': 'Polygon',
        ...    'coordinates': [[[-109, 31], [-102, 31], [-102, 37], [-109, 37], [-109, 31]]]}
        >>> all_us_cities = FeatureCollection('d1349cc2d8854d998aa6da92dc2bd24')  # doctest: +SKIP
        >>> filtered_cities = all_us_cities.filter(properties=(p.name.like("S%")))  # doctest: +SKIP
        >>> filtered_cities_fc = filtered_cities.copy(name='filtered-cities',
        ...    title='My Filtered US Cities Vector Collection',
        ...    description='A collection of cities in the US')  # doctest: +SKIP
        >>> filtered_cities_fc.wait_for_copy(timeout=120)  # doctest: +SKIP
        """
        job = CopyJob(self.id, self.vector_client)
        job.wait_for_completion(timeout)

    def delete_features(self):
        """
        Apply a filter to a product and delete features that match the filter criteria,
        taking into account calls to `FeatureCollection.filter()`.  Cannot be used with
        calls to `FeatureCollection.limit()`

        A query of some sort must be set, otherwise a BadRequestError will be raised.

        Delete jobs occur asynchronously and can take a long time to complete. You
        can access `FeatureCollection.features()` while a delete job is running,
        but you cannot issue another `FeatureCollection.delete_features()` until
        the current job has completed running.  Use `DeleteJob.wait_for_completion()`
        to block until the job is done.

        Parameters
        ----------
        vectors.async_job.DeleteJob
            A new `DeleteJob`.

        Example
        -------
        >>> from descarteslabs.vectors import FeatureCollection
        >>> aoi_geometry = {
        ...    'type': 'Polygon',
        ...    'coordinates': [[[-109, 31], [-102, 31], [-102, 37], [-109, 37], [-109, 31]]]}
        >>> fc = FeatureCollection('d1349cc2d8854d998aa6da92dc2bd24')  # doctest: +SKIP
        >>> fc.filter(geometry=aoi_geometry)  # doctest: +SKIP
        >>> delete_job = fc.delete_features()  # doctest: +SKIP
        >>> delete_job.wait_for_completion()  # doctest: +SKIP
        """
        if self._query_limit:
            raise InvalidQueryException("limits cannot be used when deleting features")

        params = dict(
            product_id=self.id,
            geometry=self._query_geometry,
            query_expr=self._query_property_expression,
        )

        product = self.vector_client.delete_features_from_query(**params).data
        return DeleteJob(product.id)

    def _repr_json_(self):
        return DotDict((k, v) for k, v in self.__dict__.items() if k in FeatureCollection.ATTRIBUTES)

    def __repr__(self):
        return "FeatureCollection({})".format(repr(self._repr_json_()))

    def __deepcopy__(self, memo):
        cls = self.__class__
        result = cls.__new__(cls)
        memo[id(self)] = result
        for k, v in self.__dict__.items():
            if k in ['_vector_client']:
                setattr(result, k, v)
            else:
                setattr(result, k, copy.deepcopy(v, memo))
        return result
