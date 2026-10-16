// Compile the form job scripts the way Jenkins runs them (CPS transform), without running them.
// Catches what the declarative validator does not (e.g. the spread operator *.). Run in the script console
// or: java -jar jenkins-cli.jar ... groovy = < jenkins/cps-compile-check.groovy
// FW_CPS_DIR (env of the Jenkins process) overrides the directory; default: this repo on the controller.
import org.codehaus.groovy.control.CompilerConfiguration
import org.codehaus.groovy.control.customizers.ImportCustomizer
def cl = jenkins.model.Jenkins.get().pluginManager.uberClassLoader
def T = cl.loadClass('com.cloudbees.groovy.cps.CpsTransformer')
new File(System.getenv('FW_CPS_DIR') ?: '/opt/jenkinscode/os-firewall-automation/jenkins/jobs').eachFileMatch(~/.*\.groovy/) { f ->
  def cc = new CompilerConfiguration(); def ic = new ImportCustomizer(); ic.addImports('com.cloudbees.groovy.cps.NonCPS')
  cc.addCompilationCustomizers(ic, T.newInstance())
  try { new GroovyShell(cl, new Binding(), cc).parse(f.text, 'WorkflowScript'); println "${f.name}: CPS compile OK" }
  catch (e) { println "${f.name}: ${e.message.readLines().findAll { it.contains('WorkflowScript') }.join(' | ')}" }
}
