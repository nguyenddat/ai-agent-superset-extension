from ...common.exceptions import ServiceUnavailableError, ValidationError


class SemanticLayerUnavailableError(ServiceUnavailableError):
    message = "Không kết nối được tới Semantic Layer."


class SemanticLayerRefusedError(ValidationError):
    message = "Semantic Layer từ chối yêu cầu."
