pipeline {
    agent any

    parameters {
        booleanParam(name: 'REINDEX', defaultValue: false, description: 'Re-indexer ChromaDB (cocher si les règles ont changé)')
    }

    environment {
        REGISTRY = '10.0.0.10:5000'
        IMAGE = 'judge'
        TAG = "${BUILD_NUMBER}"
    }

    stages {
        stage('Checkout') {
            steps {
                git branch: 'master', url: 'https://github.com/Zeatop/Judge.git'
            }
        }

        stage('SonarQube Analysis') {
            steps {
                withSonarQubeEnv('SonarQube') {
                    sh """
                        docker run --rm \
                            -v \$(pwd):/usr/src \
                            -w /usr/src \
                            -e SONAR_HOST_URL=\$SONAR_HOST_URL \
                            -e SONAR_TOKEN=\$SONAR_AUTH_TOKEN \
                            sonarsource/sonar-scanner-cli \
                            -Dsonar.projectKey=Judge \
                            -Dsonar.sources=. \
                            -Dsonar.exclusions=env/**,rules/**,test_model/**,chroma_db/**,k8s/** \
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

        stage('Stop Judge for Indexing') {
            when { expression { params.REINDEX } }
            steps {
                sh "kubectl scale deployment judge --replicas=0"
                sh "kubectl rollout status deployment/judge --timeout=60s"
            }
        }

        stage('Index ChromaDB') {
            when { expression { params.REINDEX } }
            steps {
                sh """
                    kubectl delete job judge-indexer --ignore-not-found
                    sed -i 's|${REGISTRY}/${IMAGE}:latest|${REGISTRY}/${IMAGE}:${TAG}|' k8s/indexer-job.yaml
                    kubectl apply -f k8s/indexer-job.yaml
                    kubectl wait --for=condition=complete job/judge-indexer --timeout=600s
                """
            }
        }

        stage('Deploy to K8s') {
            steps {
                withCredentials([
                    string(credentialsId: 'JUDGE_DATABASE_URL', variable: 'DATABASE_URL'),
                    string(credentialsId: 'JUDGE_MONGO_URI', variable: 'MONGO_URI'),
                    string(credentialsId: 'ANTHROPIC_API_KEY', variable: 'ANTHROPIC_API_KEY'),
                    string(credentialsId: 'DEEPSEEK_API_KEY', variable: 'DEEPSEEK_API_KEY'),
                    string(credentialsId: 'GOOGLE_JUDGE_CLIENT_ID', variable: 'GOOGLE_CLIENT_ID'),
                    string(credentialsId: 'GOOGLE_JUDGE_CLIENT_SECRET', variable: 'GOOGLE_CLIENT_SECRET'),
                    string(credentialsId: 'DISCORD_JUDGE_CLIENT_ID', variable: 'DISCORD_CLIENT_ID'),
                    string(credentialsId: 'DISCORD_JUDGE_CLIENT_SECRET', variable: 'DISCORD_CLIENT_SECRET'),
                    string(credentialsId: 'ADMIN_EMAILS', variable: 'ADMIN_EMAILS'),
                ]) {
                    sh """
                        kubectl delete secret judge-secrets --ignore-not-found
                        kubectl create secret generic judge-secrets \
                            --from-literal=JUDGE_DATABASE_URL="\$DATABASE_URL" \
                            --from-literal=API_BASE_URL="https://api.judgeai.app" \
                            --from-literal=MONGO_URI="\$MONGO_URI" \
                            --from-literal=ANTHROPIC_API_KEY="\$ANTHROPIC_API_KEY" \
                            --from-literal=DEEPSEEK_API_KEY="\$DEEPSEEK_API_KEY" \
                            --from-literal=LLM_PROVIDER="claude" \
                            --from-literal=LLM_MODEL="claude-opus-4-6" \
                            --from-literal=AUTH_SECRET_KEY="\$(openssl rand -hex 32)" \
                            --from-literal=FRONTEND_URL="https://judgeai.app" \
                            --from-literal=GOOGLE_JUDGE_CLIENT_ID="\$GOOGLE_CLIENT_ID" \
                            --from-literal=GOOGLE_JUDGE_CLIENT_SECRET="\$GOOGLE_CLIENT_SECRET" \
                            --from-literal=DISCORD_JUDGE_CLIENT_ID="\$DISCORD_CLIENT_ID" \
                            --from-literal=DISCORD_JUDGE_CLIENT_SECRET="\$DISCORD_CLIENT_SECRET" \
                            --from-literal=ADMIN_EMAILS="\$ADMIN_EMAILS"
                    """
                }
                sh "sed -i 's|${REGISTRY}/${IMAGE}:latest|${REGISTRY}/${IMAGE}:${TAG}|' k8s/deployment.yaml"
                sh "kubectl apply -f k8s/deployment.yaml"
                sh "kubectl rollout status deployment/judge --timeout=180s"
            }
        }
    }

    post {
        success {
            echo "Déploiement réussi ! Judge accessible sur le port 30091"
        }
        failure {
            sh "kubectl scale deployment judge --replicas=1 || true"
            echo "Le pipeline a échoué — Judge relancé par sécurité"
        }
    }
}