from django.http import HttpResponse

def health_check(request):
    """Simple health check endpoint for load balancers"""
    return HttpResponse("OK", status=200)
