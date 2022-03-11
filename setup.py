import pathlib
from setuptools import setup

HERE = pathlib.Path(__file__).parent
README = (HERE / "README.md").read_text()

setup(
    name="susc",
    version="0.5.4",
    description="AMOGUS SUS description language compiler",
    long_description=README,
    long_description_content_type="text/markdown",
    url="https://github.com/amogus-api/susc",
    author="portasynthinca3",
    author_email="portasynthinca3@gmail.com",
    license="BSD 3-Clause",
    packages=["susc"],
    keywords=["api", "protocol"],
    install_requires=["lark", "colorama", "markdown", "watchgod"],
    include_package_data=True,
    entry_points = {
        'console_scripts': ['susc=susc.__main__:main'],
    }
)
