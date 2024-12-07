deleteDir() {
    if [ -d $1 ]; then rm -rf $1; fi
}
deleteFile() {
    if [ -f $1 ]; then rm -f $1; fi
}
echo "Cleaning ..."
deleteDir .pytest_cache
deleteDir allure-results
deleteDir allure-report
deleteDir htmlcov
deleteDir build
deleteDir dist
deleteDir icloudpy.egg-info
deleteFile .coverage
deleteFile coverage.xml

echo "Ruffing ..." &&
    ruff check --fix &&
    echo "Testing ..." &&
    pytest &&
    echo "Reporting ..." &&
    allure generate --clean &&
    echo "Building the distribution ..." &&
    python setup.py sdist bdist_wheel &&
    echo "Done."
