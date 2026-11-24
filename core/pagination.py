from rest_framework.pagination import PageNumberPagination


class StudentListPagination(PageNumberPagination):
    """The per-student lists on the student page (spec 0019)."""
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100
