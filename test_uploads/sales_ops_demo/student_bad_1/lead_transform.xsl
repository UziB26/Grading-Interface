<?xml version="1.0" encoding="UTF-8"?>
<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform">
  <xsl:output method="xml" indent="yes"/>
  <xsl:template match="/leads">
    <export>
      <xsl:apply-templates select="lead"/>
    </export>
  </xsl:template>
  <xsl:template match="lead">
    <lead>
      <id><xsl:value-of select="@id"/></id>
      <region><xsl:value-of select="region"/></region>
      <status><xsl:value-of select="status"/></status>
    </lead>
  </xsl:template>
</xsl:stylesheet>
