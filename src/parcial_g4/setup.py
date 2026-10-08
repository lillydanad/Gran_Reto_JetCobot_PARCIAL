from setuptools import find_packages, setup

package_name = 'parcial_g4'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Grupo 4',
    maintainer_email='lillydanad@gmail.com',
    description='Gran Reto JetCobot (Grupo 4)',
    license='Apache-2.0',
    entry_points={
        'console_scripts': [
            'interprete_ordenes = parcial_g4.interprete_ordenes:main',
            'cliente_orden = parcial_g4.cliente_orden:main',
            'transcriptor_voz = parcial_g4.transcriptor_voz:main',
        ],
    },
)
