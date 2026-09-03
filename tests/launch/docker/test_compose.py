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


def test_ulimits_scalar_form():
    flags, _, _, errs, warns = service_to_docker_args(
        {"image": "i", "ulimits": {"rtprio": 99, "memlock": -1}})
    assert errs == [] and warns == []
    assert "--ulimit" in flags
    pairs = [flags[i + 1] for i, f in enumerate(flags) if f == "--ulimit"]
    assert sorted(pairs) == ["memlock=-1", "rtprio=99"]


def test_ulimits_soft_hard_mapping_form():
    flags, _, _, errs, _ = service_to_docker_args(
        {"image": "i", "ulimits": {"nofile": {"soft": 1024, "hard": 4096}}})
    assert errs == []
    assert flags[flags.index("--ulimit") + 1] == "nofile=1024:4096"


def test_mechanical_key_needs_no_bespoke_branch():
    # snake_case -> --kebab-case, singularised when repeatable
    flags, _, _, errs, _ = service_to_docker_args(
        {"image": "i", "shm_size": "2gb", "sysctls": {"net.core.somaxconn": 1024},
         "group_add": ["dialout"]})
    assert errs == []
    assert flags[flags.index("--shm-size") + 1] == "2gb"
    assert flags[flags.index("--sysctl") + 1] == "net.core.somaxconn=1024"
    assert flags[flags.index("--group-add") + 1] == "dialout"


def test_boolean_key_emits_a_bare_flag():
    flags, _, _, errs, _ = service_to_docker_args(
        {"image": "i", "init": True, "read_only": True, "tty": False})
    assert errs == []
    assert "--init" in flags and "--read-only" in flags
    assert "--tty" not in flags


def test_extra_hosts_uses_colon_not_equals():
    flags, _, _, errs, _ = service_to_docker_args(
        {"image": "i", "extra_hosts": {"gateway": "10.0.0.1"}})
    assert errs == []
    assert flags[flags.index("--add-host") + 1] == "gateway:10.0.0.1"


def test_unknown_key_is_a_readable_error_not_a_docker_flag():
    flags, _, _, errs, _ = service_to_docker_args({"image": "i", "ulimit": 99})
    assert not any(f.startswith("--ulimit") for f in flags)
    assert len(errs) == 1
    assert "ulimit" in errs[0] and "ulimits" in errs[0]   # did-you-mean


def test_unknown_key_with_no_close_match_still_errors():
    _, _, _, errs, _ = service_to_docker_args({"image": "i", "frobnicate": 1})
    assert any("frobnicate" in e for e in errs)


def test_orchestrator_only_keys_warn_with_a_reason():
    _, _, _, errs, warns = service_to_docker_args(
        {"image": "i", "build": {"context": "."}, "container_name": "x",
         "profiles": ["dev"]})
    assert errs == []
    assert any("build" in w for w in warns)
    assert any("container_name" in w for w in warns)
    assert any("profiles" in w for w in warns)


def test_compose_only_lifecycle_hooks_warn_rather_than_error():
    # A real compose file may carry these; they are compose's business,
    # not an unknown key the author got wrong.
    _, _, _, errs, warns = service_to_docker_args(
        {"image": "i", "attach": False, "post_start": [{"command": "x"}],
         "pre_stop": [{"command": "y"}], "blkio_config": {"weight": 300}})
    assert errs == []
    assert len(warns) == 4


def test_label_file_and_cgroup_translate():
    flags, _, _, errs, _ = service_to_docker_args(
        {"image": "i", "label_file": "./labels", "cgroup": "host"})
    assert errs == []
    assert flags[flags.index("--label-file") + 1] == "./labels"
    assert flags[flags.index("--cgroupns") + 1] == "host"
