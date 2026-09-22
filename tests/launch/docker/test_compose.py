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


def test_relative_bind_sources_resolve_against_base_dir():
    # sheppyd's cwd is arbitrary, so ./ and ~ bind sources are anchored to
    # the manifest (inline) or compose file (compose) directory (#33).
    flags, _, _, errs, _ = service_to_docker_args(
        {"image": "i", "volumes": [
            "./maps:/maps:ro",
            ".:/app",                            # the common compose idiom
            "../shared:/shared",
            {"type": "bind", "source": "./cfg", "target": "/cfg", "read_only": True},
            "data:/data",                        # named volume, untouched
            "/abs:/abs",                         # absolute, untouched
            "/anon"]},                           # anonymous, untouched
        base_dir="/proj/ws")
    assert errs == []
    vols = [flags[i + 1] for i, f in enumerate(flags) if f == "-v"]
    assert vols == ["/proj/ws/maps:/maps:ro", "/proj/ws:/app", "/proj/shared:/shared",
                    "/proj/ws/cfg:/cfg:ro", "data:/data", "/abs:/abs", "/anon"]


def test_tilde_bind_source_expands_home(monkeypatch):
    monkeypatch.setenv("HOME", "/home/me")
    flags, _, _, _, _ = service_to_docker_args(
        {"image": "i", "volumes": ["~/bags:/bags"]}, base_dir="/proj")
    assert flags[flags.index("-v") + 1] == "/home/me/bags:/bags"


def test_relative_env_file_resolves_against_base_dir():
    flags, _, _, errs, _ = service_to_docker_args(
        {"image": "i", "env_file": "./ros.env"}, base_dir="/proj")
    assert errs == []
    assert flags[flags.index("--env-file") + 1] == "/proj/ros.env"
    flags, _, _, _, _ = service_to_docker_args(
        {"image": "i", "env_file": ["./a.env", "/etc/b.env"]}, base_dir="/proj")
    assert [flags[i + 1] for i, f in enumerate(flags) if f == "--env-file"] \
        == ["/proj/a.env", "/etc/b.env"]


def test_label_file_and_cgroup_translate():
    flags, _, _, errs, _ = service_to_docker_args(
        {"image": "i", "label_file": "./labels", "cgroup": "host"})
    assert errs == []
    assert flags[flags.index("--label-file") + 1] == "./labels"
    assert flags[flags.index("--cgroupns") + 1] == "host"


def _gpu_service(**device):
    return {"image": "i", "deploy": {"resources": {"reservations": {
        "devices": [{"driver": "nvidia", "capabilities": ["gpu"], **device}]}}}}


def test_deploy_gpu_reservation_count_all():
    # the standard compose GPU shape; dropping it silently ran on CPU (#60)
    flags, _, _, errs, warns = service_to_docker_args(_gpu_service(count="all"))
    assert errs == [] and warns == []
    assert flags[flags.index("--gpus") + 1] == "all"


def test_deploy_gpu_reservation_count_n():
    flags, _, _, errs, _ = service_to_docker_args(_gpu_service(count=2))
    assert errs == []
    assert flags[flags.index("--gpus") + 1] == "2"


def test_deploy_gpu_reservation_device_ids():
    flags, _, _, errs, _ = service_to_docker_args(
        _gpu_service(device_ids=["0", "GPU-abc"]))
    assert errs == []
    assert flags[flags.index("--gpus") + 1] == '"device=0,GPU-abc"'


def test_deploy_gpu_reservation_without_count_means_all():
    flags, _, _, errs, _ = service_to_docker_args(_gpu_service())
    assert errs == []
    assert flags[flags.index("--gpus") + 1] == "all"


def test_deploy_gpu_extra_capabilities_are_carried():
    # a container needing NVENC must not silently lose 'video'; docker's
    # CSV wants the capabilities field quoted, not the whole argument
    flags, _, _, errs, _ = service_to_docker_args(
        _gpu_service(count="all", capabilities=["gpu", "compute", "video"]))
    assert errs == []
    assert flags[flags.index("--gpus") + 1] == 'all,"capabilities=compute,video"'
    flags, _, _, errs, _ = service_to_docker_args(
        _gpu_service(device_ids=["0"], capabilities=["gpu", "compute"]))
    assert errs == []
    assert flags[flags.index("--gpus") + 1] == '"device=0","capabilities=compute"'


def test_deploy_gpu_count_and_device_ids_together_is_an_error():
    flags, _, _, errs, _ = service_to_docker_args(
        _gpu_service(count=1, device_ids=["0"]))
    assert "--gpus" not in flags
    assert any("count" in e and "device_ids" in e for e in errs)


def test_deploy_device_entry_must_be_a_mapping():
    svc = {"image": "i", "deploy": {"resources": {"reservations": {
        "devices": ["nvidia"]}}}}
    flags, _, _, errs, _ = service_to_docker_args(svc)   # must not raise
    assert "--gpus" not in flags
    assert any("devices" in e and "mapping" in e for e in errs)


def test_deploy_device_without_gpu_capability_warns():
    svc = {"image": "i", "deploy": {"resources": {"reservations": {
        "devices": [{"driver": "tpu", "capabilities": ["tpu"]}]}}}}
    flags, _, _, errs, warns = service_to_docker_args(svc)
    assert errs == []
    assert "--gpus" not in flags
    assert any("devices" in w and "gpu" in w for w in warns)


def test_other_deploy_keys_warn():
    svc = {"image": "i", "deploy": {
        "replicas": 1, "mode": "global",
        "resources": {"limits": {"cpus": "0.5"},
                      "reservations": {"memory": "1G"}}}}
    flags, _, _, errs, warns = service_to_docker_args(svc)
    assert errs == []
    assert "--gpus" not in flags
    assert any("'deploy.mode'" in w for w in warns)
    assert any("'deploy.resources.limits'" in w for w in warns)
    assert any("'deploy.resources.reservations.memory'" in w for w in warns)
    assert not any("'deploy.replicas'" in w for w in warns)


def _values(flags, flag):
    return [flags[i + 1] for i, f in enumerate(flags) if f == flag]


def test_environment_values_are_spelled_as_yaml_not_python():
    flags, _, _, errs, _ = service_to_docker_args(
        {"image": "i", "environment": {"DEBUG": True, "RATE": 30,
                                       "GAIN": 1.5, "NAME": "x"}})
    assert errs == []
    assert _values(flags, "-e") == ["DEBUG=true", "RATE=30", "GAIN=1.5",
                                    "NAME=x"]


def test_null_environment_value_passes_the_host_value_through():
    # compose: `FOO:` with no value takes FOO from the host environment,
    # which docker run spells as a bare -e FOO
    flags, _, _, errs, _ = service_to_docker_args(
        {"image": "i", "environment": {"FOO": None, "BAR": "1"}})
    assert errs == []
    assert _values(flags, "-e") == ["FOO", "BAR=1"]


def test_list_form_environment_matches_the_mapping_form():
    flags, _, _, errs, _ = service_to_docker_args(
        {"image": "i", "environment": ["DEBUG=true", "FOO"]})
    assert errs == []
    assert _values(flags, "-e") == ["DEBUG=true", "FOO"]


def test_label_values_follow_the_same_rules():
    flags, _, _, errs, _ = service_to_docker_args(
        {"image": "i", "labels": {"com.example.rt": True, "com.example.n": 2,
                                  "com.example.flag": None}})
    assert errs == []
    assert _values(flags, "--label") == ["com.example.rt=true",
                                         "com.example.n=2", "com.example.flag"]


def test_list_form_entrypoint_leads_the_command():
    # compose semantics: --entrypoint takes the first element, the rest
    # go in front of the command
    flags, _, command, errs, _ = service_to_docker_args(
        {"image": "i", "entrypoint": ["/bin/sh", "-c"], "command": "echo hi"})
    assert errs == []
    assert flags[flags.index("--entrypoint") + 1] == "/bin/sh"
    assert "/bin/sh -c" not in flags
    assert command == ["-c", "echo", "hi"]


def test_string_entrypoint_is_split_like_command():
    flags, _, command, errs, _ = service_to_docker_args(
        {"image": "i", "entrypoint": "/bin/sh -c", "command": ["echo", "hi"]})
    assert errs == []
    assert flags[flags.index("--entrypoint") + 1] == "/bin/sh"
    assert command == ["-c", "echo", "hi"]


def test_empty_entrypoint_overrides_the_image_default():
    flags, _, command, errs, _ = service_to_docker_args(
        {"image": "i", "entrypoint": [], "command": "echo hi"})
    assert errs == []
    assert flags[flags.index("--entrypoint") + 1] == ""
    assert command == ["echo", "hi"]
