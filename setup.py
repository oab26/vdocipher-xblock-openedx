from setuptools import setup, find_packages

setup(
    name='vdocipher-xblock',
    version='1.1.3',
    description='VdoCipher DRM video player XBlock for Open edX',
    author='VAI',
    packages=find_packages(),
    install_requires=[
        'xblock',
        'requests',
    ],
    entry_points={
        'xblock.v1': [
            'vdocipher = vdocipher_xblock.xblock:VdoCipherXBlock',
        ]
    },
    package_data={
        'vdocipher_xblock': [
            'static/css/*.css',
            'static/js/*.js',
            'static/html/*.html',
        ],
    },
)
