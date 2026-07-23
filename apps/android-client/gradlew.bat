@ECHO OFF
SETLOCAL
SET DIRNAME=%~dp0
IF "%JAVA_HOME%"=="" (
  ECHO JAVA_HOME is required. 1>&2
  EXIT /B 1
)
"%JAVA_HOME%\bin\java.exe" -classpath "%DIRNAME%gradle\wrapper\gradle-wrapper.jar" org.gradle.wrapper.GradleWrapperMain %*
ENDLOCAL
