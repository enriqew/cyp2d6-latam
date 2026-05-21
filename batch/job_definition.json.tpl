{
  "_comment": [
    "AWS Batch Job Definition template for the CYP2D6 per-sample worker.",
    "",
    "This is an envsubst template — do NOT register it directly.",
    "batch/deploy.sh instantiates it automatically.",
    "",
    "To instantiate manually:",
    "  export AWS_ACCOUNT_ID=123456789012",
    "  export AWS_REGION=us-east-1",
    "  export JOB_ROLE_ARN=$(aws iam get-role --role-name cyp2d6-latam-batch-job-role --query Role.Arn --output text)",
    "  export OUTPUT_BUCKET=1000genomes-cyp2d6-results",
    "  envsubst < batch/job_definition.json.tpl > /tmp/job_definition_resolved.json",
    "  aws batch register-job-definition --cli-input-json file:///tmp/job_definition_resolved.json"
  ],
  "jobDefinitionName": "cyp2d6-process-sample",
  "type": "container",
  "containerProperties": {
    "image": "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/cyp2d6-latam-batch:latest",
    "vcpus": 2,
    "memory": 4096,
    "jobRoleArn": "${JOB_ROLE_ARN}",
    "environment": [
      {
        "name": "OUTPUT_BUCKET",
        "value": "${OUTPUT_BUCKET}"
      },
      {
        "name": "OUTPUT_PREFIX",
        "value": "results"
      }
    ],
    "logConfiguration": {
      "logDriver": "awslogs",
      "options": {
        "awslogs-group": "/aws/batch/cyp2d6-latam",
        "awslogs-region": "${AWS_REGION}",
        "awslogs-stream-prefix": "cyp2d6"
      }
    },
    "mountPoints": [],
    "volumes": [],
    "readonlyRootFilesystem": false,
    "privileged": false
  },
  "retryStrategy": {
    "attempts": 2,
    "evaluateOnExit": [
      {
        "onExitCode": "1",
        "action": "RETRY"
      },
      {
        "onReason": "CannotPullContainerError:*",
        "action": "RETRY"
      }
    ]
  },
  "timeout": {
    "attemptDurationSeconds": 7200
  },
  "tags": {
    "project": "cyp2d6-latam",
    "pipeline": "batch-scale-up"
  }
}
