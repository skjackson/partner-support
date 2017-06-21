// jenkins DSL job for zendesk_org_add python script

package org.edx.jenkins.dsl

import static org.edx.jenkins.dsl.DevopsTasks.common_read_permissions
import static org.edx.jenkins.dsl.YAMLHelpers.parseYaml
import org.yaml.snakeyaml.error.YAMLException

Map secureConfig = [:]

try {
    secureConfig = parseYaml('@Partner-Support-Secure/jenkins/settings.yml', this)
} catch (YAMLException e) {
    throw new IllegalArgumentException("@Partner-Support-Secure/jenkins/settings.yml: ${e.message}")
}

jobName = 'zendesk_org_add'


// job("${secureConfig['folder_name']}/${jobName}")
job(jobName) {

environmentVariables {
        env('ZENDESK_EMAIL', secureConfig['ZENDESK_EMAIL'])
        env('ZENDESK_TOKEN', secureConfig['ZENDESK_TOKEN'])
        env('LMS_HOST', secureConfig['LMS_HOST'])
        env('LMS_USER', secureConfig['LMS_USER'])
        env('LMS_PW', secureConfig['LMS_PW'])
        env('LMS_DBNAME', secureConfig['LMS_DBNAME'])
        env('EDGE_HOST', secureConfig['EDGE_HOST'])
        env('EDGE_PW', secureConfig['EDGE_PW'])
        env('WH_HOST', secureConfig['WH_HOST'])
        env('WH_USER', secureConfig['WH_USER'])
        env('WH_PW', secureConfig['WH_PW'])
    }
    
multiscm {
       git {
            remote {
                url('https://github.com/edx/partner-support.git')
            }

triggers {
        cron('30 * * * *')  // Every day at the 30 minute mark of the hour
    }

    steps {
        virtualenv {
            name(jobName)
            pythonName('System-CPython-3.5')
            nature('shell')
            // command readFileFromWorkspace('jenkins-job-dsl-internal/resources/sync-sailthru-content.sh')
            command readFileFromWorkspace('partner-support/resources/zendesk_org_add.sh')
        }
    }
}    

