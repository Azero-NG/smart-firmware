import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.const import CONF_ID

DEPENDENCIES = ["esp8266", "network"]

ct30w_stock_ota_ns = cg.esphome_ns.namespace("ct30w_stock_ota")
CT30WStockOTA = ct30w_stock_ota_ns.class_("CT30WStockOTA", cg.Component)

CONFIG_SCHEMA = cv.Schema(
    {cv.GenerateID(): cv.declare_id(CT30WStockOTA)}
).extend(cv.COMPONENT_SCHEMA)


async def to_code(config):
    var = cg.new_Pvariable(config[CONF_ID])
    await cg.register_component(var, config)
    cg.add_library("ESP8266HTTPClient", None)
