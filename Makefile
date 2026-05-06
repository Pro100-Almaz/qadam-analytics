REG=ghcr.io
OWNER=pro100-almaz
IMAGE=$(REG)/$(OWNER)/qadam-analytics

SHA := $(shell git rev-parse --short=7 HEAD)
TAG ?= sha-$(SHA)

login:
	echo "$$GHCR_TOKEN" | docker login $(REG) -u $(OWNER) --password-stdin

build:
	docker compose build --pull appseed-app

push: build
	docker tag qadam-analytics-appseed-app $(IMAGE):$(TAG)
	docker tag qadam-analytics-appseed-app $(IMAGE):latest
	docker push $(IMAGE):$(TAG)
	docker push $(IMAGE):latest

print:
	@echo "Image: $(IMAGE):$(TAG)"

# --- SSL (first time only) ---
cert-init:
	docker compose run --rm certbot certonly \
		--webroot -w /var/www/certbot \
		-d $(NGINX_SERVER_NAME) \
		--email $(CERT_EMAIL) \
		--agree-tos --no-eff-email

cert-renew:
	docker compose run --rm certbot renew --webroot -w /var/www/certbot
