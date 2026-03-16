from setuptools import setup

package_name = 'rtsp_bridge'

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
    description='RTSP to ROS2 Image Topic Bridge',
    license='Apache-2.0',
    entry_points={
        'console_scripts': [
            'rtsp_bridge_node = rtsp_bridge.rtsp_bridge_node:main',
        ],
    },
)
