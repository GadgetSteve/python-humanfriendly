# Human friendly input/output in Python.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: June 24, 2017
# URL: https://humanfriendly.readthedocs.io

"""
Utility classes and functions that make it easy to write :mod:`unittest` compatible test suites.

Over the years I've developed the habit of writing test suites for Python
projects using the :mod:`unittest` module. During those years I've come to know
pytest_ and in fact I use pytest to run my test suites (due to its much better
error reporting) but I've yet to publish a test suite that *requires* pytest.
I have several reasons for doing so:

- It's nice to keep my test suites as simple and accessible as possible and
  not requiring a specific test runner is part of that attitude.

- Whereas :mod:`unittest` is quite explicit, pytest contains a lot of magic,
  which kind of contradicts the Python mantra "explicit is better than
  implicit" (IMHO).

.. _pytest: https://docs.pytest.org
"""

# Standard library module
import logging
import os
import pipes
import shutil
import sys
import tempfile
import time
import unittest

# Modules included in our package.
from humanfriendly.compat import StringIO
from humanfriendly.text import compact, random_string

# Initialize a logger for this module.
logger = logging.getLogger(__name__)

# A unique object reference used to detect missing attributes.
NOTHING = object()

# Public identifiers that require documentation.
__all__ = (
    'CallableTimedOut',
    'CaptureOutput',
    'ContextManager',
    'CustomSearchPath',
    'MockedProgram',
    'PatchedAttribute',
    'PatchedItem',
    'TemporaryDirectory',
    'TestCase',
    'retry',
    'run_cli',
)


def retry(func, timeout=60, exc_type=AssertionError):
    """retry(func, timeout=60, exc_type=AssertionError)
    Retry a function until assertions no longer fail.

    :param func: A callable. When the callable returns
                 :data:`False` it will also be retried.
    :param timeout: The number of seconds after which to abort (a number,
                    defaults to 60).
    :param exc_type: The type of exceptions to retry (defaults
                     to :exc:`~exceptions.AssertionError`).
    :returns: The value returned by `func`.
    :raises: Once the timeout has expired :func:`retry()` will raise the
             previously retried assertion error. When `func` keeps returning
             :data:`False` until `timeout` expires :exc:`CallableTimedOut`
             will be raised.

    This function sleeps between retries to avoid claiming CPU cycles we don't
    need. It starts by sleeping for 0.1 second but adjusts this to one second
    as the number of retries grows.
    """
    pause = 0.1
    timeout += time.time()
    while True:
        try:
            result = func()
            if result is not False:
                return result
        except exc_type:
            if time.time() > timeout:
                raise
        else:
            if time.time() > timeout:
                raise CallableTimedOut()
        time.sleep(pause)
        if pause < 1:
            pause *= 2


def run_cli(entry_point, *arguments, **options):
    """
    Test a command line entry point.

    :param entry_point: The function that implements the command line interface
                        (a callable).
    :param arguments: Any positional arguments (strings) become the command
                      line arguments (:data:`sys.argv` items 1-N).
    :param options: The following keyword arguments are supported:

                    **input**
                     Refer to :class:`CaptureOutput`.
                    **merged**
                     Refer to :class:`CaptureOutput`.
                    **program_name**
                     Used to set :data:`sys.argv` item 0.
    :returns: A tuple with two values:

              1. The return code (an integer).
              2. The captured output (a string).
    """
    program_name = options.pop('program_name', sys.executable)
    # Start capturing the standard output and error streams.
    with CaptureOutput(**options) as output:
        # Temporarily override sys.argv.
        arguments = list(arguments)
        arguments.insert(0, program_name)
        with PatchedAttribute(sys, 'argv', arguments):
            try:
                # Call the command line interface.
                entry_point()
            except SystemExit as e:
                # Intercept sys.exit() calls.
                returncode = e.code
            else:
                returncode = 0
            return returncode, output.getvalue()


class CallableTimedOut(Exception):

    """Raised by :func:`retry()` when the timeout expires."""


class ContextManager(object):

    """Base class to enable composition of context managers."""

    def __enter__(self):
        """Enable use as context managers."""
        return self

    def __exit__(self, exc_type=None, exc_value=None, traceback=None):
        """Enable use as context managers."""


class PatchedAttribute(ContextManager):

    """Context manager that temporary replaces an object attribute using :func:`setattr()`."""

    def __init__(self, obj, name, value):
        """
        Initialize a :class:`PatchedAttribute` object.

        :param obj: The object to patch.
        :param name: An attribute name.
        :param value: The value to set.
        """
        self.object_to_patch = obj
        self.attribute_to_patch = name
        self.patched_value = value
        self.original_value = NOTHING

    def __enter__(self):
        """
        Replace (patch) the attribute.

        :returns: The object whose attribute was patched.
        """
        # Enable composition of context managers.
        super(PatchedAttribute, self).__enter__()
        # Patch the object's attribute.
        self.original_value = getattr(self.object_to_patch, self.attribute_to_patch, NOTHING)
        setattr(self.object_to_patch, self.attribute_to_patch, self.patched_value)
        return self.object_to_patch

    def __exit__(self, exc_type=None, exc_value=None, traceback=None):
        """Restore the attribute to its original value."""
        # Enable composition of context managers.
        super(PatchedAttribute, self).__exit__(exc_type, exc_value, traceback)
        # Restore the object's attribute.
        if self.original_value is NOTHING:
            delattr(self.object_to_patch, self.attribute_to_patch)
        else:
            setattr(self.object_to_patch, self.attribute_to_patch, self.original_value)


class PatchedItem(ContextManager):

    """Context manager that temporary replaces an object item using :func:`~object.__setitem__()`."""

    def __init__(self, obj, item, value):
        """
        Initialize a :class:`PatchedItem` object.

        :param obj: The object to patch.
        :param item: The item to patch.
        :param value: The value to set.
        """
        self.object_to_patch = obj
        self.item_to_patch = item
        self.patched_value = value
        self.original_value = NOTHING

    def __enter__(self):
        """
        Replace (patch) the item.

        :returns: The object whose item was patched.
        """
        # Enable composition of context managers.
        super(PatchedItem, self).__enter__()
        # Patch the object's item.
        try:
            self.original_value = self.object_to_patch[self.item_to_patch]
        except KeyError:
            self.original_value = NOTHING
        self.object_to_patch[self.item_to_patch] = self.patched_value
        return self.object_to_patch

    def __exit__(self, exc_type=None, exc_value=None, traceback=None):
        """Restore the item to its original value."""
        # Enable composition of context managers.
        super(PatchedItem, self).__exit__(exc_type, exc_value, traceback)
        # Restore the object's item.
        if self.original_value is NOTHING:
            del self.object_to_patch[self.item_to_patch]
        else:
            self.object_to_patch[self.item_to_patch] = self.original_value


class TemporaryDirectory(ContextManager):

    """
    Easy temporary directory creation & cleanup using the :keyword:`with` statement.

    Here's an example of how to use this:

    .. code-block:: python

       with TemporaryDirectory() as directory:
           # Do something useful here.
           assert os.path.isdir(directory)
    """

    def __init__(self, **options):
        """
        Initialize a :class:`TemporaryDirectory` object.

        :param options: Any keyword arguments are passed on to
                        :func:`tempfile.mkdtemp()`.
        """
        self.mkdtemp_options = options
        self.temporary_directory = None

    def __enter__(self):
        """
        Create the temporary directory using :func:`tempfile.mkdtemp()`.

        :returns: The pathname of the directory (a string).
        """
        # Enable composition of context managers.
        super(TemporaryDirectory, self).__enter__()
        # Create the temporary directory.
        self.temporary_directory = tempfile.mkdtemp(**self.mkdtemp_options)
        return self.temporary_directory

    def __exit__(self, exc_type=None, exc_value=None, traceback=None):
        """Cleanup the temporary directory using :func:`shutil.rmtree()`."""
        # Enable composition of context managers.
        super(TemporaryDirectory, self).__exit__(exc_type, exc_value, traceback)
        # Cleanup the temporary directory.
        if self.temporary_directory is not None:
            shutil.rmtree(self.temporary_directory)
            self.temporary_directory = None


class CustomSearchPath(PatchedItem, TemporaryDirectory):

    """
    Context manager to temporarily customize ``$PATH`` (the executable search path).

    This class is a composition of the :class:`PatchedItem` and
    :class:`TemporaryDirectory` context managers.
    """

    def __init__(self, isolated=False):
        """
        Initialize a :class:`CustomSearchPath` object.

        :param isolated: :data:`True` to clear the original search path,
                         :data:`False` to add the temporary directory to the
                         start of the search path.
        """
        # Initialize our own instance variables.
        self.isolated_search_path = isolated
        # Selectively initialize our superclasses.
        PatchedItem.__init__(self, os.environ, 'PATH', self.current_search_path)
        TemporaryDirectory.__init__(self)

    def __enter__(self):
        """
        Activate the custom ``$PATH``.

        :returns: The pathname of the directory that has
                  been added to ``$PATH`` (a string).
        """
        # Get the temporary directory.
        directory = TemporaryDirectory.__enter__(self)
        # Override the value to patch now that we have
        # the pathname of the temporary directory.
        self.patched_value = (
            directory if self.isolated_search_path
            else os.pathsep.join([directory] + self.current_search_path.split(os.pathsep))
        )
        # Temporary patch the $PATH.
        PatchedItem.__enter__(self)
        # Pass the pathname of the temporary directory to the caller
        # because they may want to `install' custom executables.
        return directory

    def __exit__(self, exc_type=None, exc_value=None, traceback=None):
        """Deactivate the custom ``$PATH``."""
        super(CustomSearchPath, self).__exit__(exc_type, exc_value, traceback)

    @property
    def current_search_path(self):
        """The value of ``$PATH`` or :data:`os.defpath` (a string)."""
        return os.environ.get('PATH', os.defpath)


class MockedProgram(CustomSearchPath):

    """
    Context manager to mock the existence of a program (executable).

    This class extends the functionality of :class:`CustomSearchPath`.
    """

    def __init__(self, name, returncode=0):
        """
        Initialize a :class:`MockedProgram` object.

        :param name: The name of the program (a string).
        :param returncode: The return code that the program should emit (a
                           number, defaults to zero).
        """
        # Initialize our own instance variables.
        self.program_name = name
        self.program_returncode = returncode
        self.program_signal_file = None
        # Initialize our superclasses.
        super(MockedProgram, self).__init__()

    def __enter__(self):
        """
        Create the mock program.

        :returns: The pathname of the directory that has
                  been added to ``$PATH`` (a string).
        """
        directory = super(MockedProgram, self).__enter__()
        self.program_signal_file = os.path.join(directory, 'program-was-run-%s' % random_string(10))
        pathname = os.path.join(directory, self.program_name)
        with open(pathname, 'w') as handle:
            handle.write('#!/bin/sh\n')
            handle.write('echo > %s\n' % pipes.quote(self.program_signal_file))
            handle.write('exit %i\n' % self.program_returncode)
        os.chmod(pathname, 0o755)
        return directory

    def __exit__(self, *args, **kw):
        """
        Ensure that the mock program was run.

        :raises: :exc:`~exceptions.AssertionError` when
                 the mock program hasn't been run.
        """
        try:
            assert self.program_signal_file and os.path.isfile(self.program_signal_file), \
                ("It looks like %r was never run!" % self.program_name)
        finally:
            return super(MockedProgram, self).__exit__(*args, **kw)


class CaptureOutput(ContextManager):

    """Context manager that captures what's written to :data:`sys.stdout` and :data:`sys.stderr`."""

    def __init__(self, merged=False, input=''):
        """
        Initialize a :class:`CaptureOutput` object.

        :param merged: :data:`True` to merge the streams,
                       :data:`False` to capture them separately.
        :param input: The data that reads from :data:`sys.stdin`
                      should return (a string).
        """
        self.stdin = StringIO(input)
        self.stdout = StringIO()
        self.stderr = self.stdout if merged else StringIO()
        self.patched_attributes = [
            PatchedAttribute(sys, name, getattr(self, name))
            for name in ('stdin', 'stdout', 'stderr')
        ]

    stdin = None
    """The :class:`~humanfriendly.compat.StringIO` object used to feed the standard input stream."""

    stdout = None
    """The :class:`~humanfriendly.compat.StringIO` object used to capture the standard output stream."""

    stderr = None
    """The :class:`~humanfriendly.compat.StringIO` object used to capture the standard error stream."""

    def __enter__(self):
        """Start capturing what's written to :data:`sys.stdout` and :data:`sys.stderr`."""
        super(CaptureOutput, self).__enter__()
        for context in self.patched_attributes:
            context.__enter__()
        return self

    def __exit__(self, exc_type=None, exc_value=None, traceback=None):
        """Stop capturing what's written to :data:`sys.stdout` and :data:`sys.stderr`."""
        super(CaptureOutput, self).__exit__(exc_type, exc_value, traceback)
        for context in self.patched_attributes:
            context.__exit__(exc_type, exc_value, traceback)

    def getvalue(self):
        """Get the text written to :data:`sys.stdout`."""
        return self.stdout.getvalue()


class TestCase(unittest.TestCase):

    """Subclass of :class:`unittest.TestCase` with automatic logging and other miscellaneous features."""

    def setUp(self, log_level=logging.DEBUG):
        """setUp(log_level=logging.DEBUG)
        Automatically configure logging to the terminal.

        :param log_level: The log verbosity (a number, defaults to
                          :data:`logging.DEBUG`).

        The :func:`setUp()` method is automatically called by
        :class:`unittest.TestCase` before each test method starts.
        It does two things:

        - When :mod:`coloredlogs` is installed :func:`coloredlogs.install()`
          will be used to configure logging to the terminal. When this fails
          with an :exc:`~exceptions.ImportError` then
          :func:`logging.basicConfig()` is used as a fall back.

        - Before the test method starts a newline is emitted, to separate the
          name of the test method (which will be printed to the terminal by
          :mod:`unittest` and/or pytest_) from the first line of logging output
          that the test method is likely going to generate.
        """
        # Configure logging to the terminal.
        try:
            import coloredlogs
            coloredlogs.install(level=log_level)
        except ImportError:
            logging.basicConfig(
                level=log_level,
                format='%(asctime)s %(name)s[%(process)d] %(levelname)s %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S')
        # Separate the name of the test method (printed by the superclass
        # and/or py.test without a newline at the end) from the first line of
        # logging output that the test method is likely going to generate.
        sys.stderr.write("\n")

    def assertRaises(self, exception, callable, *args, **kwds):
        """
        Replacement for :func:`unittest.TestCase.assertRaises()` that returns the exception.

        Refer to the :func:`unittest.TestCase.assertRaises()` documentation for
        details on argument handling. The return value is the caught exception.

        This method does not support use as a context manager.
        """
        try:
            callable(*args, **kwds)
        except exception as e:
            # Return the expected exception as a regular return value.
            return e
        else:
            # Raise an exception when no exception was raised :-).
            assert False, "Expected an exception to be raised!"

    def skipTest(self, text, *args, **kw):
        """
        Enable backwards compatible "marking of tests to skip".

        By calling this method from a return statement in the test to be
        skipped, that test can be marked as skipped when possible, without
        breaking the test suite when :func:`unittest.TestCase.skipTest()`
        isn't available (in Python 2.6 and 3.0).
        """
        reason = compact(text, *args, **kw)
        try:
            super(TestCase, self).skipTest(reason)
        except AttributeError:
            logger.warning("%s", reason)
