REG=ghcr.io
OWNER=pro100-almaz
IMAGE=$(REG)/$(OWNER)/qadam-analytics

SHA := $(shell git rev-parse --short=7 HEAD)
TAG ?= sha-$(SHA)

login:
	echo "$$GHCR_TOKEN" | docker login $(REG) -u <your-github-username> --password-stdin

build:
	TAG=$(TAG) docker compose -f docker-compose.yml build --pull appseed-app

push: build
	TAG=$(TAG) docker compose -f docker-compose.yml push appseed-app

print:
	@echo "Pushed: $(IMAGE):$(TAG)"

