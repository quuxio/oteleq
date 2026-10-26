python3 -m venv .venv
.venv/bin/python -m pip install --require-hashes --only-binary=:all: -r requirements-dev.txt -r requirements.txt
npm ci --ignore-scripts --no-audit
make java-check node-check go-check test sonar-policy
mvn -q -f adapters/java/pom.xml org.apache.maven.plugins:maven-dependency-plugin:3.11.0:copy-dependencies -DincludeScope=test -DoutputDirectory=target/dependency

