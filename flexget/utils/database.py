from datetime import datetime
from sqlalchemy import extract, func, case
from sqlalchemy.orm import synonym
from sqlalchemy.ext.hybrid import Comparator, hybrid_property
from flexget.manager import Session
from flexget.utils import qualities


def with_session(func):
    """"A decorator which creates a session if one was not passed via keyword argument to the function.

    Automatically commits and closes the session if one was created, caller is responsible for commit if passed in.
    """

    def wrapper(*args, **kwargs):
        if not kwargs.get('session'):
            kwargs['session'] = Session(autoflush=True, expire_on_commit=False)
            try:
                result = func(*args, **kwargs)
                kwargs['session'].commit()
                return result
            finally:
                kwargs['session'].close()
        else:
            return func(*args, **kwargs)
    return wrapper


def pipe_list_synonym(name):
    """Converts pipe separated text into a list"""

    def getter(self):
        attr = getattr(self, name)
        if attr:
            return attr.strip('|').split('|')

    def setter(self, value):
        if isinstance(value, basestring):
            setattr(self, name, value)
        else:
            setattr(self, name, '|'.join(value))

    return synonym(name, descriptor=property(getter, setter))


def text_date_synonym(name):
    """Converts Y-M-D date strings into datetime objects"""

    def getter(self):
        return getattr(self, name)

    def setter(self, value):
        if isinstance(value, basestring):
            setattr(self, name, datetime.strptime(value, '%Y-%m-%d'))
        else:
            setattr(self, name, value)

    return synonym(name, descriptor=property(getter, setter))


def safe_pickle_synonym(name):
    """Used to store Entry instances into a PickleType column in the database.

    In order to ensure everything can be loaded after code changes, makes sure no custom python classes are pickled.
    """

    def only_builtins(item):
        """Casts all subclasses of builtin types to their builtin python type. Works recursively on iterables.

        Raises ValueError if passed an object that doesn't subclass a builtin type.
        """

        supported_types = [str, unicode, int, float, bool, datetime]
        # dict, list, tuple and set are also supported, but handled separately

        if type(item) in supported_types:
            return item
        elif isinstance(item, dict):
            result = {}
            for key, value in item.iteritems():
                try:
                    result[key] = only_builtins(value)
                except TypeError:
                    continue
            return result
        elif isinstance(item, (list, tuple, set)):
            result = []
            for value in item:
                try:
                    result.append(only_builtins(value))
                except ValueError:
                    continue
            if isinstance(item, list):
                return result
            elif isinstance(item, tuple):
                return tuple(result)
            else:
                return set(result)
        else:
            for s_type in supported_types:
                if isinstance(item, s_type):
                    return s_type(item)

        # If item isn't a subclass of a builtin python type, raise ValueError.
        raise TypeError('%r is not a subclass of a builtin python type.' % type(item))

    def getter(self):
        return getattr(self, name)

    def setter(self, entry):
        setattr(self, name, only_builtins(entry))

    return synonym(name, descriptor=property(getter, setter))


class CaseInsensitiveWord(Comparator):
    """Hybrid value representing a lower case representation of a word."""

    def __init__(self, word):
        if isinstance(word, basestring):
            self.word = word.lower()
        elif isinstance(word, CaseInsensitiveWord):
            self.word = word.word
        else:
            self.word = func.lower(word)

    def operate(self, op, other):
        if not isinstance(other, CaseInsensitiveWord):
            other = CaseInsensitiveWord(other)
        return op(self.word, other.word)

    def __clause_element__(self):
        return self.word

    def __str__(self):
        return self.word


class QualityComparator(Comparator):
    """Database quality comparator fields which can operate against quality objects or their string equivalents."""

    def operate(self, op, other):
        if hasattr(other, 'value'):
            value = other.value
        elif isinstance(other, basestring):
            qual = qualities.get(other, False)
            if qual:
                value = qual.value
            else:
                raise ValueError('%s is not a valid quality' % other)
        else:
            raise TypeError('%r cannot be compared to a quality' % other)

        whens = dict((quality.name, quality.value) for quality in qualities.all())
        return op(case(value=self.__clause_element__(), whens=whens, else_=0), value)


def quality_property(text_attr):

    def getter(self):
        return qualities.get(getattr(self, text_attr))

    def setter(self, value):
        if isinstance(value, basestring):
            setattr(self, text_attr, value)
        else:
            setattr(self, text_attr, value.name)

    def comparator(self):
        return QualityComparator(getattr(self, text_attr))

    prop = hybrid_property(getter, setter)
    prop.comparator(comparator)
    return prop


def ignore_case_property(text_attr):

    def getter(self):
        return CaseInsensitiveWord(getattr(self, text_attr))

    def setter(self, value):
        setattr(self, text_attr, value)

    return hybrid_property(getter, setter)


def year_property(date_attr):

    def getter(self):
        date = getattr(self, date_attr)
        return date and date.year

    def expr(cls):
        return extract('year', getattr(cls, date_attr))

    return hybrid_property(getter, expr=expr)
