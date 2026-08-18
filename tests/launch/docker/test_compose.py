from sheppy.launch.docker.compose import service_to_docker_args


def test_common_ros_service():
    svc = {"image": "org/perc:1", "command": "ros2 launch perc up.py",
           "environment": {"RMW_IMPLEMENTATION": "rmw_cyclonedds_cpp"},
           "network_mode": "host", "ipc": "host",
           "devices": ["/dev/video0:/dev/video0"],
           "volumes": ["/opt/maps:/maps:ro"]}
    flags, image, command, errs, warns = service_to_docker_args(svc)
    assert errs == []
    assert image == "org/perc:1"
    assert command == ["ros2", "launch", "perc", "up.py"]
    assert "--network" in flags and "host" in flags
    assert flags[flags.index("--ipc") + 1] == "host"
    assert "-v" in flags and "/opt/maps:/maps:ro" in flags
    assert "--device" in flags and "/dev/video0:/dev/video0" in flags
    assert flags[flags.index("-e") + 1] == "RMW_IMPLEMENTATION=rmw_cyclonedds_cpp"


def test_missing_image_is_error():
    _, _, _, errs, _ = service_to_docker_args({"command": "x"})
    assert any("image" in e for e in errs)


def test_replicas_gt_one_is_error():
    _, _, _, errs, _ = service_to_docker_args(
        {"image": "i", "deploy": {"replicas": 3}})
    assert any("replicas" in e for e in errs)


def test_inapplicable_keys_warn():
    _, _, _, errs, warns = service_to_docker_args(
        {"image": "i", "restart": "always", "depends_on": ["db"]})
    assert errs == []
    assert any("restart" in w for w in warns)
    assert any("depends_on" in w for w in warns)


def test_environment_list_form_and_volume_longform():
    flags, _, _, _, _ = service_to_docker_args(
        {"image": "i", "environment": ["A=1", "B=2"],
         "volumes": [{"source": "/s", "target": "/t", "read_only": True}]})
    assert flags[flags.index("-e") + 1] == "A=1"
    assert "/s:/t:ro" in flags


def test_long_form_ports_is_a_hard_error():
    _, _, _, errs, _ = service_to_docker_args(
        {"image": "i", "ports": [{"target": 80, "published": 8080}]})
    assert any("ports" in e for e in errs)


def test_long_form_gpus_is_a_hard_error():
    _, _, _, errs, _ = service_to_docker_args(
        {"image": "i", "gpus": [{"capabilities": ["gpu"]}]})
    assert any("gpus" in e for e in errs)


def test_short_form_ports_and_gpus_still_work():
    flags, _, _, errs, _ = service_to_docker_args(
        {"image": "i", "ports": ["8080:80"], "gpus": "all"})
    assert errs == []
    assert flags[flags.index("-p") + 1] == "8080:80"
    assert flags[flags.index("--gpus") + 1] == "all"
