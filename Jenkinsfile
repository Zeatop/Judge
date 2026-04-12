pipeline {
    agent any

    environment {
        REGISTRY = '10.0.0.10:5000'
        IMAGE = 'judge'
        TAG = "${BUILD_NUMBER}"
    }

    stages {
        stage('Checkout') {
            steps {
                git branch: 'main', url: 'https://github.com/Zeatop/Judge.git'
            }
        }

        stage('SonarQube Analysis') {
            steps {
                withSonarQubeEnv('SonarQube') {
                    sh """
                        docker run --rm \
                            --volumes-from jenkins \
                            -w /var/jenkins_home/workspace/Judge \
                            -e SONAR_HOST_URL=\$SONAR_HOST_URL \
                            -e SONAR_TOKEN=\$SONAR_AUTH_TOKEN \
                            sonarsource/sonar-scanner-cli \
                            -Dsonar.projectKey=Judge \
                            -Dsonar.sources=src \
                            -Dsonar.host.url=\$SONAR_HOST_URL \
                            -Dsonar.token=\$SONAR_AUTH_TOKEN
                    """
                }
            }
        }

        stage('Docker Build') {
            steps {
                sh "docker build -t ${REGISTRY}/${IMAGE}:${TAG} -t ${REGISTRY}/${IMAGE}:latest ."
            }
        }

        stage('Docker Push') {
            steps {
                sh "docker push ${REGISTRY}/${IMAGE}:${TAG}"
                sh "docker push ${REGISTRY}/${IMAGE}:latest"
            }
        }

        stage('Deploy to K8s') {
            steps {
                sh "sed -i 's|${REGISTRY}/${IMAGE}:latest|${REGISTRY}/${IMAGE}:${TAG}|' k8s/deployment.yaml"
                sh 'kubectl apply -f k8s/deployment.yaml'
                sh 'kubectl rollout status deployment/judge --timeout=120s'
            }
        }
    }

    post {
        success {
            echo "Déploiement réussi ! Judge accessible sur le port 30090"
        }
        failure {
            echo "Le pipeline a échoué"
        }
    }
}
