Zagon broker:
1. Poveži se na zerotier
docker-compose up -d

Zagon producer (v /Producer):
1. Pri broker = "" vstavi IP od brokerja (dobljen iz Zerotier)
2. docker build -f Dockerfile.producer -t producer .
	2.1 Force reinstall: docker build --no-cache -f Dockerfile.server -t server .
3. docker run --rm producer

Zagon producer (v /Producer):
1. Pri broker = "" vstavi IP od brokerja (dobljen iz Zerotier)
2. docker build -f Dockerfile.consumer -t consumer .
3. docker run --rm consumer
