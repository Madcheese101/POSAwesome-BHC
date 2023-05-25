# -*- coding: utf-8 -*-
# Copyright (c) 2020, Youssef Restom and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import json
import frappe
from frappe import _
from erpnext.accounts.doctype.pos_profile.pos_profile import get_item_groups


@frappe.whitelist()
def get_items(pos_profile, price_list=None, item_size="", item_group="", search_value=""):
    data = dict()
    pos_profile = json.loads(pos_profile)
    if not price_list:
        price_list = pos_profile.get("selling_price_list")
   
    if search_value:
        data = search_serial_or_batch_or_barcode_number(search_value)

    posa_display_items_in_stock =  pos_profile.get("posa_display_items_in_stock")
    search_serial_no =  pos_profile.get("posa_search_serial_no")
    posa_show_template_items = pos_profile.get("posa_show_template_items")

    item_code = data.get("item_code") if data.get("item_code") else search_value
    serial_no = data.get("serial_no") if data.get("serial_no") else ""
    batch_no = data.get("batch_no") if data.get("batch_no") else ""
    barcode = data.get("barcode") if data.get("barcode") else ""
   
    condition = get_conditions(item_code, serial_no, batch_no, barcode)
    
    condition += get_item_group_condition(pos_profile.get("name"))
    
    if not posa_show_template_items:
        condition += " AND i.has_variants = 0"

    result = []

    if(item_size):
         condition += " AND c.attribute_value like '%{item_size}%'".format(item_size=item_size)
    if(item_group):
         condition += " AND i.item_group like '%{item_group}%'".format(item_group=item_group)
         

    items_data = frappe.db.sql(
        """
        SELECT
            i.name AS item_code,
            i.item_name,
            i.description,
            i.stock_uom,
            i.image,
            i.is_stock_item,
            i.has_variants,
            i.variant_of,
            i.item_group,
            i.idx as idx,
            i.has_batch_no,
            i.has_serial_no,
            i.max_discount,
            i.brand
        FROM
            `tabItem` i, `tabItem Variant Attribute` c
        WHERE
                i.disabled = 0
                AND i.is_sales_item = 1
                AND i.is_fixed_asset = 0
                AND i.item_code = c.parent
                AND c.attribute like '%المقاس%'
                {condition}
        ORDER BY
            i.item_name asc, c.attribute_value asc
        LIMIT 300
            """.format(
            condition=condition,
        ),
        as_dict=1,
    )

    if items_data:
        items = [d.item_code for d in items_data]
        item_prices_data = frappe.get_all(
            "Item Price",
            fields=["item_code", "price_list_rate", "currency", "uom"],
            filters={
                "price_list": price_list,
                "item_code": ["in", items],
                "currency": pos_profile.get("currency"),
                "selling": 1,
            },
        )

        item_prices = {}
        for d in item_prices_data:
            item_prices.setdefault(d.item_code, {})
            item_prices[d.item_code][d.get("uom") or "None"] = d

        for item in items_data:
            item_code = item.item_code
            item_price = {}
            serial_no_data = []
            attributes = ""
            item_attributes = ""
            item_barcode = frappe.get_all(
                "Item Barcode",
                filters={"parent": item_code},
                fields=["barcode", "posa_uom"],
            )        
            
            if item_prices.get(item_code):
                item_price = (
                    item_prices.get(item_code).get(item.stock_uom)
                    or item_prices.get(item_code).get("None")
                    or {}
                )

            if search_serial_no:
                serial_no_data = frappe.get_all(
                    "Serial No",
                    filters={"item_code": item_code, "status": "Active"},
                    fields=["name as serial_no"],
                )
            if posa_display_items_in_stock:
                item_stock_qty = get_stock_availability(
                    item_code, pos_profile.get("warehouse")
                )

            if posa_show_template_items and item.has_variants:
                attributes = get_item_attributes(item.item_code)
            if posa_show_template_items and item.variant_of:
                item_attributes = frappe.get_all(
                    "Item Variant Attribute",
                    fields=["attribute", "attribute_value"],
                    filters={"parent": item.item_code, "parentfield": "attributes"},
                )
            if posa_display_items_in_stock and ( not item_stock_qty or item_stock_qty < 0):
                pass
            else:
                row = {}
                row.update(item)
                row.update(
                    {
                        "rate": item_price.get("price_list_rate") or 0,
                        "currency": item_price.get("currency")
                        or pos_profile.get("currency"),
                        "item_barcode": item_barcode or [],
                        "actual_qty": item_stock_qty or 0,
                        "serial_no_data": serial_no_data or [],
                        "attributes": attributes or "",
                        "item_attributes": item_attributes or "",
                    }
                )
                result.append(row)
    return result


def get_item_group_condition(pos_profile):
    cond = "and 1=1"
    item_groups = get_item_groups(pos_profile)
    if item_groups:
        cond = "and item_group in (%s)" % (", ".join(["%s"] * len(item_groups)))

    return cond % tuple(item_groups)

@frappe.whitelist()
def get_items_groups():
    return frappe.db.get_list(
        'Item Group',
        filters={'parent_item_group':["descendants of","Products - منتجات"], "is_group": 0},
        order_by='name asc'
    )


def get_stock_availability(item_code, warehouse):
    actual_qty = (
        frappe.db.get_value(
            "Stock Ledger Entry",
            filters={
                "item_code": item_code,
                "warehouse": warehouse,
                "is_cancelled": 0,
            },
            fieldname="qty_after_transaction",
            order_by="posting_date desc, posting_time desc, creation desc",
        )
        or 0.0
    )
    return actual_qty

def build_item_cache(item_code):
    parent_item_code = item_code

    attributes = [
        a.attribute
        for a in frappe.db.get_all(
            "Item Variant Attribute",
            {"parent": parent_item_code},
            ["attribute"],
            order_by="idx asc",
        )
    ]

    item_variants_data = frappe.db.get_all(
        "Item Variant Attribute",
        {"variant_of": parent_item_code},
        ["parent", "attribute", "attribute_value"],
        order_by="name",
        as_list=1,
    )

    disabled_items = set([i.name for i in frappe.db.get_all("Item", {"disabled": 1})])

    attribute_value_item_map = frappe._dict({})
    item_attribute_value_map = frappe._dict({})

    item_variants_data = [r for r in item_variants_data if r[0] not in disabled_items]
    for row in item_variants_data:
        item_code, attribute, attribute_value = row
        # (attr, value) => [item1, item2]
        attribute_value_item_map.setdefault((attribute, attribute_value), []).append(
            item_code
        )
        # item => {attr1: value1, attr2: value2}
        item_attribute_value_map.setdefault(item_code, {})[attribute] = attribute_value

    optional_attributes = set()
    for item_code, attr_dict in item_attribute_value_map.items():
        for attribute in attributes:
            if attribute not in attr_dict:
                optional_attributes.add(attribute)

    frappe.cache().hset(
        "attribute_value_item_map", parent_item_code, attribute_value_item_map
    )
    frappe.cache().hset(
        "item_attribute_value_map", parent_item_code, item_attribute_value_map
    )
    frappe.cache().hset("item_variants_data", parent_item_code, item_variants_data)
    frappe.cache().hset("optional_attributes", parent_item_code, optional_attributes)


def get_item_optional_attributes(item_code):
    val = frappe.cache().hget("optional_attributes", item_code)

    if not val:
        build_item_cache(item_code)

    return frappe.cache().hget("optional_attributes", item_code)


@frappe.whitelist()
def get_item_attributes(item_code):
    attributes = frappe.db.get_all(
        "Item Variant Attribute",
        fields=["attribute"],
        filters={"parenttype": "Item", "parent": item_code},
        order_by="idx asc",
    )

    optional_attributes = get_item_optional_attributes(item_code)

    for a in attributes:
        values = frappe.db.get_all(
            "Item Attribute Value",
            fields=["attribute_value", "abbr"],
            filters={"parenttype": "Item Attribute", "parent": a.attribute},
            order_by="idx asc",
        )
        a.values = values
        if a.attribute in optional_attributes:
            a.optional = True

    return attributes

@frappe.whitelist()
def search_serial_or_batch_or_barcode_number(search_value):
	# search barcode no
	barcode_data = frappe.db.get_value('Item Barcode', {'barcode': search_value}, ['barcode', 'parent as item_code'], as_dict=True)
	if barcode_data:
		return barcode_data

	# search serial no
	serial_no_data = frappe.db.get_value('Serial No', search_value, ['name as serial_no', 'item_code'], as_dict=True)
	if serial_no_data:
		return serial_no_data

	# search batch no
	batch_no_data = frappe.db.get_value('Batch', search_value, ['name as batch_no', 'item as item_code'], as_dict=True)
	if batch_no_data:
		return batch_no_data

	return {}

def get_conditions(item_code, serial_no, batch_no, barcode):
	
	if serial_no or batch_no or barcode:
		return "and i.name = {0}".format(frappe.db.escape(item_code))

	return ("""and (i.name like {item_code} or i.item_name like {item_code})"""
				.format(item_code=frappe.db.escape('%' + item_code + '%')))
