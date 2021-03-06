import time

from descarteslabs.client.services.cache import cached
from descarteslabs.client.services.storage import Storage

client = Storage()


@cached(client, minimum_runtime=2.0)
def f(s):
    time.sleep(s)
    return s


print(f(1))
print(f(2))
print(f(3))
