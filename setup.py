import os
import re
import sys
import fnmatch
import os.path

# for command line options and supported environment variables, please
# see the end of 'setupinfo.py'

if (2, 7) != sys.version_info[:2] < (3, 5):
    print("This lxml version requires Python 2.7, 3.5 or later.")
    sys.exit(1)

try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup


# Windows: strip whole-program-optimisation / link-time-code-generation from
# distutils' hard-coded MSVC defaults.
#
# distutils' MSVCCompiler.initialize() compiles with '/GL' and links with
# '/LTCG'.  We link against the prebuilt static libs from
# lxml/libxml2-win-binaries (libxml2_a.lib, libxslt_a.lib, libexslt_a.lib,
# iconv_a.lib), which were produced by a different MSVC toolchain and carry
# '/GL' objects whose PDBs the LTCG pass cannot read.  The link then dies with
#   iconv.c : fatal error C1090: PDB API call failed, error code '5'
#   LINK : fatal error LNK1257: code generation failed
# Appending an override is not enough: distutils puts its own '/LTCG' at the
# *front* of the link command line, where it beats a trailing '/LTCG:OFF'.
# The flags have to be removed from the defaults instead, so we patch
# initialize() and scrub the instance's flag lists after it has run.
def _patch_msvc_disable_ltcg():
    if sys.platform != 'win32':
        return

    _msvccompiler = None
    for _import in ('setuptools._distutils', 'distutils'):
        try:
            _msvccompiler = __import__(
                _import + '._msvccompiler', fromlist=['_msvccompiler'])
        except ImportError:
            continue
        else:
            break
    if _msvccompiler is None:
        return

    compiler_class = getattr(_msvccompiler, 'MSVCCompiler', None)
    if compiler_class is None:
        return

    def strip_ltcg_flags(compiler):
        """Remove '/GL' from compile flags and '/LTCG*' from link flags."""
        for attr_name in dir(compiler):
            if not (attr_name.startswith('compile_options')
                    or attr_name.startswith('ldflags')):
                continue
            flags = getattr(compiler, attr_name, None)
            if not isinstance(flags, list):
                continue
            cleaned = [
                flag for flag in flags
                if flag.upper() != '/GL'
                and not flag.upper().startswith('/LTCG')
            ]
            if cleaned != flags:
                setattr(compiler, attr_name, cleaned)

    original_initialize = compiler_class.initialize

    def initialize(self, *args, **kwargs):
        result = original_initialize(self, *args, **kwargs)
        strip_ltcg_flags(self)
        return result

    compiler_class.initialize = initialize
    print("Patched MSVCCompiler.initialize() to drop /GL and /LTCG "
          "(prebuilt libxml2/libxslt/libiconv static libs break LTCG: "
          "C1090 -> LNK1257).")


_patch_msvc_disable_ltcg()

# make sure Cython finds include files in the project directory and not outside
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

import versioninfo
import setupinfo

# override these and pass --static for a static build. See
# doc/build.txt for more information. If you do not pass --static
# changing this will have no effect.
def static_env_list(name, separator=None):
    return [x.strip() for x in os.environ.get(name, "").split(separator) if x.strip()]

STATIC_INCLUDE_DIRS = static_env_list("LXML_STATIC_INCLUDE_DIRS", separator=os.pathsep)
STATIC_LIBRARY_DIRS = static_env_list("LXML_STATIC_LIBRARY_DIRS", separator=os.pathsep)
STATIC_CFLAGS = static_env_list("LXML_STATIC_CFLAGS")
STATIC_BINARIES = static_env_list("LXML_STATIC_BINARIES", separator=os.pathsep)

# create lxml-version.h file
versioninfo.create_version_h()
lxml_version = versioninfo.version()
print("Building lxml version %s." % lxml_version)

OPTION_RUN_TESTS = setupinfo.has_option('run-tests')

branch_link = """
After an official release of a new stable series, bug fixes may become
available at
https://github.com/lxml/lxml/tree/lxml-%(branch_version)s .
Running ``easy_install lxml==%(branch_version)sbugfix`` will install
the unreleased branch state from
https://github.com/lxml/lxml/tarball/lxml-%(branch_version)s#egg=lxml-%(branch_version)sbugfix
as soon as a maintenance branch has been established.  Note that this
requires Cython to be installed at an appropriate version for the build.

"""

if versioninfo.is_pre_release():
    branch_link = ""


extra_options = {}
if 'setuptools' in sys.modules:
    extra_options['zip_safe'] = False
    extra_options['python_requires'] = (
        # NOTE: keep in sync with Trove classifier list below.
        '>=2.7, !=3.0.*, !=3.1.*, !=3.2.*, !=3.3.*, != 3.4.*')

    try:
        import pkg_resources
    except ImportError:
        pass
    else:
        f = open("requirements.txt", "r")
        try:
            deps = [str(req) for req in pkg_resources.parse_requirements(f)]
        finally:
            f.close()
        extra_options['extras_require'] = {
            'source': deps,
            'cssselect': 'cssselect>=0.7',
            'html5': 'html5lib',
            'htmlsoup': 'BeautifulSoup4',
        }

extra_options.update(setupinfo.extra_setup_args())

extra_options['package_data'] = {
    'lxml': [
        'etree.h',
        'etree_api.h',
        'lxml.etree.h',
        'lxml.etree_api.h',
        # Include Cython source files for better traceback output.
        '*.pyx',
        '*.pxi',
    ],
    'lxml.includes': [
        '*.pxd', '*.h'
        ],
    'lxml.isoschematron':  [
        'resources/rng/iso-schematron.rng',
        'resources/xsl/*.xsl',
        'resources/xsl/iso-schematron-xslt1/*.xsl',
        'resources/xsl/iso-schematron-xslt1/readme.txt'
        ],
    }

extra_options['package_dir'] = {
        '': 'src'
    }

extra_options['packages'] = [
        'lxml', 'lxml.includes', 'lxml.html', 'lxml.isoschematron'
    ]


def setup_extra_options():
    is_interesting_package = re.compile('^(libxml|libxslt|libexslt)$').match
    is_interesting_header = re.compile(r'^(zconf|zlib|.*charset)\.h$').match

    def extract_files(directories, pattern='*'):
        def get_files(root, dir_path, files):
            return [ (root, dir_path, filename)
                     for filename in fnmatch.filter(files, pattern) ]

        file_list = []
        for dir_path in directories:
            dir_path = os.path.realpath(dir_path)
            for root, dirs, files in os.walk(dir_path):
                rel_dir = root[len(dir_path)+1:]
                if is_interesting_package(rel_dir):
                    file_list.extend(get_files(root, rel_dir, files))
                elif not rel_dir:
                    # include also top-level header files (zlib/iconv)
                    file_list.extend(
                        item for item in get_files(root, rel_dir, files)
                        if is_interesting_header(item[-1])
                    )
        return file_list

    def build_packages(files):
        packages = {}
        seen = set()
        for root_path, rel_path, filename in files:
            if filename in seen:
                # libxml2/libxslt header filenames are unique
                continue
            seen.add(filename)
            package_path = '.'.join(rel_path.split(os.sep))
            if package_path in packages:
                root, package_files = packages[package_path]
                if root != root_path:
                    print("WARNING: conflicting directories found for include package '%s': %s and %s"
                          % (package_path, root_path, root))
                    continue
            else:
                package_files = []
                packages[package_path] = (root_path, package_files)
            package_files.append(filename)

        return packages

    # Copy Global Extra Options
    extra_opts = dict(extra_options)

    # Build ext modules
    ext_modules = setupinfo.ext_modules(
                    STATIC_INCLUDE_DIRS, STATIC_LIBRARY_DIRS,
                    STATIC_CFLAGS, STATIC_BINARIES)
    extra_opts['ext_modules'] = ext_modules

    packages = extra_opts.get('packages', list())
    package_dir = extra_opts.get('package_dir', dict())
    package_data = extra_opts.get('package_data', dict())

    # Add lxml.include with (lxml, libxslt headers...)
    #   python setup.py build --static --static-deps install
    #   python setup.py bdist_wininst --static
    if setupinfo.OPTION_STATIC:
        include_dirs = [] # keep them in order
        for extension in ext_modules:
            for inc_dir in extension.include_dirs:
                if inc_dir not in include_dirs:
                    include_dirs.append(inc_dir)

        header_packages = build_packages(extract_files(include_dirs))

        package_filename = "__init__.py"
        for package_path, (root_path, filenames) in header_packages.items():
            if not package_path:
                # lxml.includes -> lxml.includes.extlibs
                package_path = "extlibs"
            package = 'lxml.includes.' + package_path
            packages.append(package)

            # create '__init__.py' to make sure it's considered a package
            if package_filename not in filenames:
                with open(os.path.join(root_path, package_filename), 'wb') as f:
                    pass
                filenames.append(package_filename)

            assert package not in package_data
            package_data[package] = filenames
            assert package not in package_dir
            package_dir[package] = root_path

    return extra_opts

setup(
    name = "lxml",
    version = lxml_version,
    author="lxml dev team",
    author_email="lxml-dev@lxml.de",
    maintainer="lxml dev team",
    maintainer_email="lxml-dev@lxml.de",
    license="BSD-3-Clause",
    url="https://lxml.de/",
    # Commented out because this causes distutils to emit warnings
    # `Unknown distribution option: 'bugtrack_url'`
    # which distract folks from real causes of problems when troubleshooting
    # bugtrack_url="https://bugs.launchpad.net/lxml",
    project_urls={
        "Source": "https://github.com/lxml/lxml",
    },
    description=(
        "Powerful and Pythonic XML processing library"
        " combining libxml2/libxslt with the ElementTree API."
    ),
    long_description=((("""\
lxml is a Pythonic, mature binding for the libxml2 and libxslt libraries.  It
provides safe and convenient access to these libraries using the ElementTree
API.

It extends the ElementTree API significantly to offer support for XPath,
RelaxNG, XML Schema, XSLT, C14N and much more.

To contact the project, go to the `project home page
<https://lxml.de/>`_ or see our bug tracker at
https://launchpad.net/lxml

In case you want to use the current in-development version of lxml,
you can get it from the github repository at
https://github.com/lxml/lxml .  Note that this requires Cython to
build the sources, see the build instructions on the project home
page.  To the same end, running ``easy_install lxml==dev`` will
install lxml from
https://github.com/lxml/lxml/tarball/master#egg=lxml-dev if you have
an appropriate version of Cython installed.

""" + branch_link) % {"branch_version": versioninfo.branch_version()}) +
                      versioninfo.changes()),
    classifiers=[
        versioninfo.dev_status(),
        'Intended Audience :: Developers',
        'Intended Audience :: Information Technology',
        'License :: OSI Approved :: BSD License',
        'Programming Language :: Cython',
        # NOTE: keep in sync with 'python_requires' list above.
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
        'Programming Language :: C',
        'Operating System :: OS Independent',
        'Topic :: Text Processing :: Markup :: HTML',
        'Topic :: Text Processing :: Markup :: XML',
        'Topic :: Software Development :: Libraries :: Python Modules'
    ],

    **setup_extra_options()
)

if OPTION_RUN_TESTS:
    print("Running tests.")
    import test
    try:
        sys.exit( test.main(sys.argv[:1]) )
    except ImportError:
        pass  # we assume that the binaries were not built with this setup.py run
