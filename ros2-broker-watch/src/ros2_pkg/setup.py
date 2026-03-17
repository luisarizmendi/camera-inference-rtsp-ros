from setuptools import setup

package_name = 'image_broker'

setup(
    name=package_name,
    version='0.1.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Maintainer',
    maintainer_email='maintainer@example.com',
    description='ROS2 Image Stream Broker',
    license='Apache-2.0',
    entry_points={
        'console_scripts': [
            'image_broker_node = image_broker.image_broker_node:main',
        ],
    },
)
