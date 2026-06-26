from sheppy.manifest import Machine, Alternative, Node, Manifest


def test_construct_full_model():
    alt = Alternative(id="realsense", kind="launch_file", package="realsense2_camera",
                      launch_file="rs_launch.py", publishes=["/camera/color/image_raw"])
    node = Node(name="camera", alternatives=[alt], description="RGB-D source")
    manifest = Manifest(machines=[Machine(name="robot", host="10.0.0.20", user="r")],
                        nodes=[node])
    assert manifest.nodes[0].alternatives[0].id == "realsense"
    assert node.select == "single"  # default
    assert alt.params == {} and alt.subscribes == []  # mutable defaults isolated


def test_manifest_node_lookup():
    node = Node(name="camera", alternatives=[])
    manifest = Manifest(machines=[], nodes=[node])
    assert manifest.node("camera") is node
    assert manifest.node("missing") is None
