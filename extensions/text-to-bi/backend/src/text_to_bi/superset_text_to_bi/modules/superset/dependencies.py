from functools import wraps

from .services.srv_dataset import require_dataset


# Takes the dataset id out of the URL arguments and hands the route the dataset instead; it sits under handle_errors
# so a missing dataset answers 404.
def requires_dataset(method):
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        return method(self, *args, dataset=require_dataset(kwargs.pop("dataset_id")), **kwargs)
    return wrapper
