
import functools


def rsetattr (obj, attr, val):
    """
    Recursively sets a property on an object, splitting on the dot.
    """
    
    pre, _, post = attr.rpartition('.')
    return setattr(rgetattr(obj, pre) if pre else obj, post, val)


def rgetattr (obj, attr, *args):
    """
    Recursively gets a property from an object, splitting on the dot.
    """
    
    def _getattr(obj, attr):
        return getattr(obj, attr, *args)
    return functools.reduce(_getattr, [obj] + attr.split('.'))


def get_default (*items):
    """
    Implements itemgetter with None fallback.
    """
    
    if len(items) == 1:
        item = items.get(item, None)
        
        def g(obj):
            return obj.get(item, None)
    else:
        
        def g(obj):
            return tuple(obj.get(item, None) for item in items)
        
    return g