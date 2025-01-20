from pg_spot_operator.cli import str_to_bool, str_boolean_false_to_empty_string

# from pg_spot_operator.cli import (
#     ArgumentParser,
#     compile_manifest_from_cmdline_params,
# )
#
#
# def test_compile_manifest():
#     args: ArgumentParser = ArgumentParser()
#     args.instance_name = "x"
#     args.region = "y"
#
#     args.aws_security_group_ids = "x,y"
#     m = compile_manifest_from_cmdline_params(args)
#     assert len(m.aws.security_group_ids) == 2
#
#     args.aws_security_group_ids = ""
#     m = compile_manifest_from_cmdline_params(args)
#     assert len(m.aws.security_group_ids) == 0


def test_str_to_bool():
    assert str_to_bool("True")
    assert str_to_bool("true")
    assert str_to_bool("on")
    assert str_to_bool("yes")

    assert not str_to_bool("False")
    assert not str_to_bool("")
    assert not str_to_bool("no")


def test_str_boolean_false_to_empty_string():
    assert str_boolean_false_to_empty_string("no") == ""
    assert str_boolean_false_to_empty_string("True") == "True"
