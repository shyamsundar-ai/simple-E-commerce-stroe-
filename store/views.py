from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.contrib.auth import login
from django.shortcuts import render, redirect

from django.core.mail import send_mail
from decimal import Decimal

from django.db import transaction
from django.shortcuts import render, get_object_or_404, redirect
from django.views.decorators.http import require_POST
from django.contrib import messages

from .models import Product, Order, OrderItem


def product_list(request):
    products = Product.objects.all().order_by("-created_at")
    return render(request, "store/product_list.html", {"products": products})


def product_detail(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    return render(request, "store/product_detail.html", {"product": product})


@require_POST
def add_to_cart(request, product_id):
    product = get_object_or_404(Product, id=product_id)

    if product.stock > 0:
        cart = request.session.get("cart", {})
        key = str(product.id)
        quantity = cart.get(key, 0)

        if quantity < product.stock:
            cart[key] = quantity + 1

        request.session["cart"] = cart

    return redirect("cart_view")


def cart_view(request):
    cart = request.session.get("cart", {})
    cart_items = []
    total = Decimal("0.00")

    for product_id, quantity in cart.items():
        product = Product.objects.filter(id=product_id).first()

        if product and quantity > 0:
            subtotal = product.price * quantity
            cart_items.append({
                "product": product,
                "quantity": quantity,
                "subtotal": subtotal,
            })
            total += subtotal

    return render(request, "store/cart.html", {
        "cart_items": cart_items,
        "total": total,
    })


@require_POST
def increase_quantity(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    cart = request.session.get("cart", {})
    key = str(product.id)
    quantity = cart.get(key, 0)

    if quantity < product.stock:
        cart[key] = quantity + 1

    request.session["cart"] = cart
    return redirect("cart_view")


@require_POST
def decrease_quantity(request, product_id):
    cart = request.session.get("cart", {})
    key = str(product_id)

    if key in cart:
        if cart[key] > 1:
            cart[key] -= 1
        else:
            del cart[key]

    request.session["cart"] = cart
    return redirect("cart_view")


@require_POST
def remove_from_cart(request, product_id):
    cart = request.session.get("cart", {})
    cart.pop(str(product_id), None)
    request.session["cart"] = cart
    return redirect("cart_view")


def checkout(request):
    cart = request.session.get("cart", {})

    if not cart:
        return redirect("cart_view")

    cart_items = []
    total = Decimal("0.00")

    for product_id, quantity in cart.items():
        product = Product.objects.filter(id=product_id).first()

        if not product or quantity < 1:
            return render(request, "store/checkout.html", {
                "error": "A product in your cart is no longer available. Please review your cart.",
                "cart_items": [],
                "total": Decimal("0.00"),
            })

        cart_items.append({
            "product": product,
            "quantity": quantity,
            "subtotal": product.price * quantity,
        })
        total += product.price * quantity

    if request.method == "POST":
        name = request.POST.get("customer_name", "").strip()
        email = request.POST.get("email", "").strip()
        phone = request.POST.get("phone", "").strip()
        address = request.POST.get("address", "").strip()

        if not all([name, email, phone, address]):
            return render(request, "store/checkout.html", {
                "error": "Please fill in all the fields.",
                "cart_items": cart_items,
                "total": total,
            })

        try:
            with transaction.atomic():
                order = Order.objects.create(
                    customer_name=name,
                    email=email,
                    phone=phone,
                    address=address,
                    total_amount=total,
                    status="Pending",
                )

                for product_id, quantity in cart.items():
                    product = Product.objects.select_for_update().get(
                        id=product_id
                    )

                    if quantity < 1 or product.stock < quantity:
                        raise ValueError(
                            f"Not enough stock available for {product.name}."
                        )

                    OrderItem.objects.create(
                        order=order,
                        product=product,
                        quantity=quantity,
                        price=product.price,
                    )

                    product.stock -= quantity
                    product.save(update_fields=["stock"])

        except (Product.DoesNotExist, ValueError) as exc:
            return render(request, "store/checkout.html", {
                "error": str(exc) or "A product is no longer available.",
                "cart_items": cart_items,
                "total": total,
            })

        request.session["cart"] = {}
        return redirect("order_success", order_id=order.id)

    return render(request, "store/checkout.html", {
        "cart_items": cart_items,
        "total": total,
    })


def order_success(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    return render(request, "store/order_success.html", {"order": order})


def track_order(request):
    order = None
    error = ""

    if request.method == "POST":
        order_id = request.POST.get("order_id", "").strip()
        email = request.POST.get("email", "").strip()

        if order_id.isdigit() and email:
            order = Order.objects.filter(
                id=int(order_id),
                email__iexact=email
            ).first()

        if order is None:
            error = (
                "We couldn't find an order matching those details. "
                "Please check your order number and email."
            )

    return render(request, "store/track_order.html", {
        "order": order,
        "error": error,
    })


@require_POST
def cancel_order(request, order_id):
    try:
        with transaction.atomic():
            order = Order.objects.select_for_update().get(id=order_id)

            # Verify the customer's email before allowing cancellation.
            email = request.POST.get("email", "").strip()
            if not email or order.email.lower() != email.lower():
                messages.error(
                    request,
                    "Order not found or the email address does not match."
                )
                return redirect("track_order")

            if order.status != "Pending":
                messages.error(
                    request,
                    "Only Pending orders can be cancelled."
                )
                return redirect("order_success", order_id=order.id)

            for item in order.items.all():
                product = Product.objects.select_for_update().get(
                    id=item.product_id
                )
                product.stock += item.quantity
                product.save(update_fields=["stock"])

            order.status = "Cancelled"
            order.save(update_fields=["status"])

        messages.success(
            request,
            "Your order was cancelled and the product stock was restored."
        )
        return redirect("order_success", order_id=order_id)

    except Order.DoesNotExist:
        messages.error(request, "Order not found.")
        return redirect("track_order")
from django.http import HttpResponse
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
def download_invoice(request, order_id):
    from django.shortcuts import get_object_or_404

    order = get_object_or_404(Order, id=order_id)

    if request.method != "POST":
        return HttpResponse(
            "Please use the invoice download form.",
            status=405
        )

    email = request.POST.get("email", "").strip()

    if email.lower() != order.email.lower():
        return HttpResponse(
            "Invalid email for this order.",
            status=403
        )

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = (
        f'attachment; filename="Shyam_Store_Invoice_{order.id}.pdf"'
    )

    pdf = canvas.Canvas(response, pagesize=A4)
    width, height = A4

    y = height - 60

    pdf.setFont("Helvetica-Bold", 22)
    pdf.drawString(50, y, "SHYAM STORE")

    y -= 30
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(50, y, "ORDER INVOICE")

    y -= 35
    pdf.setFont("Helvetica", 11)
    pdf.drawString(50, y, f"Order Number: {order.id}")

    y -= 20
    pdf.drawString(
        50, y,
        f"Order Date: {order.created_at.strftime('%d-%m-%Y')}"
    )

    y -= 20
    pdf.drawString(50, y, f"Status: {order.status}")

    y -= 35
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(50, y, "Customer Details")

    y -= 20
    pdf.setFont("Helvetica", 10)
    pdf.drawString(50, y, f"Name: {order.customer_name}")
    y -= 18
    pdf.drawString(50, y, f"Email: {order.email}")
    y -= 18
    pdf.drawString(50, y, f"Phone: {order.phone}")

    y -= 18
    address_lines = order.address.splitlines() or [order.address]
    pdf.drawString(50, y, "Address:")
    y -= 16

    for line in address_lines:
        pdf.drawString(65, y, line[:90])
        y -= 15

    y -= 15
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(50, y, "Product")
    pdf.drawString(300, y, "Qty")
    pdf.drawString(350, y, "Price")
    pdf.drawString(440, y, "Subtotal")

    y -= 10
    pdf.line(50, y, 545, y)
    y -= 20

    pdf.setFont("Helvetica", 10)

    for item in order.items.select_related("product").all():
        if y < 80:
            pdf.showPage()
            y = height - 60
            pdf.setFont("Helvetica", 10)

        subtotal = item.price * item.quantity
        pdf.drawString(50, y, item.product.name[:38])
        pdf.drawString(300, y, str(item.quantity))
        pdf.drawString(350, y, f"Rs. {item.price:.2f}")
        pdf.drawString(440, y, f"Rs. {subtotal:.2f}")
        y -= 22

    y -= 10
    pdf.line(350, y, 545, y)
    y -= 25

    pdf.setFont("Helvetica-Bold", 13)
    pdf.drawString(350, y, f"Total: Rs. {order.total_amount:.2f}")

    y -= 45
    pdf.setFont("Helvetica", 10)
    pdf.drawString(50, y, "Thank you for shopping with Shyam Store!")

    pdf.save()
    return response
def register(request):
    from django.contrib.auth.forms import UserCreationForm
    from django.contrib.auth import login
    from django.contrib.auth.models import User
    from django.shortcuts import render, redirect

    if request.method == "POST":
        form = UserCreationForm(request.POST)
        username = request.POST.get("username", "").strip()

        if username and User.objects.filter(username=username).exists():
            form.add_error("username", "This username is already taken. Please choose another.")

        if form.is_valid():
            user = form.save()
            user.email = request.POST.get("email", "").strip()
            user.save()
            login(request, user)
            return redirect("product_list")
    else:
        form = UserCreationForm()

    return render(request, "registration/register.html", {"form": form})


from django.contrib.auth.decorators import login_required
from django.shortcuts import render

@login_required
def customer_profile(request):
    return render(
        request,
        "store/customer_profile.html",
        {"customer": request.user}
    )
