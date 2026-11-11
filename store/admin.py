from django.contrib import admin
from .models import Product, Order, OrderItem


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "price", "stock")
    search_fields = ("name", "category")
    list_filter = ("category",)


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ("product", "quantity", "price")
    can_delete = False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "customer_name",
        "email",
        "total_amount",
        "status",
        "created_at",
    )
    list_display_links = ("id", "customer_name")
    list_filter = ("status", "created_at")
    search_fields = ("customer_name", "email", "phone")
    readonly_fields = (
        "customer_name",
        "email",
        "phone",
        "address",
        "total_amount",
        "created_at",
    )
    inlines = [OrderItemInline]
