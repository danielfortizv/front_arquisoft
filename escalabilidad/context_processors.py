# Create a new file called context_processors.py in your escalabilidad app

def user_data(request):
    """Context processor to make user data available in all templates"""
    context = {}
    if 'usuario' in request.session:
        context['user_data'] = request.session['usuario']
    return context