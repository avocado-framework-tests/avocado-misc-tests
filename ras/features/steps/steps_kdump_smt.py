import os
import sys
from behave   import given, when, then
#from hamcrest import assert_that, equal_to
sys.path.append(os.path.abspath("/home/nasastry/avocado-misc-tests/generic/"))
from kdump import KDUMP

@given('start_kdump')
def step_impl(context):
    context.a = KDUMP()

@when('setup_kdump "{smt_value}"')
def step_impl(context, smt_value):
    context.a.setUp()
    context.a.set_smt_value(smt_value)

@then('test_kdump')
def step_impl(context):
    context.a.test()
