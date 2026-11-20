from ...common.exceptions import NotFoundError, ValidationError


class BusinessModelValidationError(ValidationError):
    pass


class TransformEdgeNotHideableError(ValidationError):
    message = "Cạnh biến đổi được khai báo trong Data Dictionary: bỏ phần Biến đổi của cột ở đó để xóa cạnh."


class DataLayerNotFoundError(NotFoundError):
    message = "Data layer not found."


class BusinessDomainNotFoundError(NotFoundError):
    message = "Business domain not found."


class DuplicateDataLayerNameError(ValidationError):
    message = "Tên tầng dữ liệu đã tồn tại."


class DuplicateBusinessDomainNameError(ValidationError):
    message = "Tên nghiệp vụ đã tồn tại."
