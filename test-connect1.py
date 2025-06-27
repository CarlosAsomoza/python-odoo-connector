import xmlrpc.client
import os
import json
import base64
import requests
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()
ODOO_URL = os.getenv("ODOO_URL")
ODOO_DB = os.getenv("ODOO_DB")
ODOO_USER = os.getenv("ODOO_USER")
ODOO_PASSWORD = os.getenv("ODOO_PASSWORD")

def conectar_odoo():
    common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common")
    uid = common.authenticate(ODOO_DB, ODOO_USER, ODOO_PASSWORD, {})
    models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object")
    return uid, models

def convertir_url_a_base64(url):
    try:
        response = requests.get(url)
        if response.status_code == 200:
            return base64.b64encode(response.content).decode("utf-8")
    except Exception as e:
        print(f"⚠️ Error al descargar imagen {url}: {e}")
    return None

def buscar_o_crear_atributo(models, uid, nombre):
    res = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
        'product.attribute', 'search', [[('name', '=', nombre)]])
    if res:
        return res[0]
    return models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
        'product.attribute', 'create', [{'name': nombre, 'create_variant': 'always'}])

def buscar_o_crear_valores(models, uid, atributo_id, valores):
    valor_ids = []
    for valor in valores:
        val = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
            'product.attribute.value', 'search',
            [[('name', '=', valor), ('attribute_id', '=', atributo_id)]])
        if val:
            valor_ids.append(val[0])
        else:
            new_id = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
                'product.attribute.value', 'create',
                [{'name': valor, 'attribute_id': atributo_id}])
            valor_ids.append(new_id)
    return valor_ids

def buscar_o_crear_categoria(models, uid, categoria, subcategoria):
    cat_id = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD, 'product.category', 'search', [[('name', '=', categoria)]])
    if not cat_id:
        cat_id = [models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD, 'product.category', 'create', [{'name': categoria}])]

    subcat_id = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD, 'product.category', 'search', [[
        ('name', '=', subcategoria), ('parent_id', '=', cat_id[0])]])
    if not subcat_id:
        subcat_id = [models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD, 'product.category', 'create', [{
            'name': subcategoria, 'parent_id': cat_id[0]}])]

    return subcat_id[0]
  
def crear_imagen_extra(models, uid, tipo, product_id, urls):
    field = 'product_tmpl_id' if tipo == 'product.template' else 'product_variant_id'
    for url in urls:
        b64 = convertir_url_a_base64(url)
        if not b64:
            continue
        models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
            'product.image', 'create', [{
                field: product_id,
                'image_1920': b64,
                'name': 'Imagen adicional'
            }])


def crear_producto_con_variantes(models, uid, producto):
    sku_padre = producto["skuPadre"]
    nombre = producto["nombrePadre"]
    hijos = producto["hijos"]
    descripcion = producto.get("descripcion", "")
    categoria = producto.get("categorias", "Otros")
    subcategoria = producto.get("subCategorias", categoria)
    img_principal = convertir_url_a_base64(producto["imagenesPadre"][0]) if producto.get("imagenesPadre") else None
    img_vector = convertir_url_a_base64(producto["imagenesVector"][0]) if producto.get("imagenesVector") else None

    colores = [hijo["color"] for hijo in hijos]
    skus_hijo = [hijo["skuHijo"] for hijo in hijos]

    atributo_id = buscar_o_crear_atributo(models, uid, "Color")
    valor_ids = buscar_o_crear_valores(models, uid, atributo_id, colores)
    categ_id = buscar_o_crear_categoria(models, uid, categoria, subcategoria)

    # Crear producto padre
    vals_template = {
        'name': nombre,
        'default_code': sku_padre,
        'type': 'consu',
        'description': descripcion,
        'description_sale': descripcion,
        'description_purchase': descripcion,
        'description_ecommerce': descripcion,
        'categ_id': categ_id,
        'attribute_line_ids': [(0, 0, {
            'attribute_id': atributo_id,
            'value_ids': [(6, 0, valor_ids)]
        })]
    }
    if img_principal:
        vals_template['image_1920'] = img_principal

    template_id = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
        'product.template', 'create', [vals_template])

    print(f"🟢 Producto creado: {nombre} (SKU: {sku_padre})")

    # Imagen vectorial como imagen adicional
    if img_vector:
        crear_imagen_extra(models, uid, 'product.template', template_id, [producto["imagenesVector"][0]])

    # Imagenes adicionales del producto padre
    if producto.get("imagenesPadre"):
        crear_imagen_extra(models, uid, 'product.template', template_id, producto["imagenesPadre"][1:])

    # Obtener IDs de variantes
    variant_ids = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
        'product.template', 'read', [template_id],
        {'fields': ['product_variant_ids']})[0]['product_variant_ids']

    for i, pid in enumerate(variant_ids):
        sku = skus_hijo[i] if i < len(skus_hijo) else f"{sku_padre}-X{i}"
        models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
            'product.product', 'write', [[pid], {'default_code': sku}])

        name = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
            'product.product', 'read', [pid], {'fields': ['name']})[0]['name']
        print(f"   ✅ Variante creada: {name} (SKU: {sku})")

        # Imagenes de la variante
        imagenes_hijo = hijos[i].get("imagenesHijo", [])
        crear_imagen_extra(models, uid, 'product.product', pid, imagenes_hijo)

def main():
    uid, models = conectar_odoo()

    with open("D:\\MozaPrint\\Odoo\\Scripts PY\\ProductSync\\sync_odoo_paquete\\products.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    if not data.get("success"):
        print("❌ Error: JSON inválido o sin éxito")
        return

    productos = data["response"]
    for producto in productos:
        crear_producto_con_variantes(models, uid, producto)

if __name__ == "__main__":
    main()

