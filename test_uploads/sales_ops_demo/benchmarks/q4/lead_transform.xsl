<?xml version="1.0" encoding="UTF-8"?>
<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform">
  <xsl:output method="xml" indent="yes"/>

  <xsl:template match="/leads">
    <lead_export>
      <xsl:apply-templates select="lead"/>
    </lead_export>
  </xsl:template>

  <xsl:template match="lead">
    <lead>
      <id><xsl:value-of select="@id"/></id>
      <region><xsl:value-of select="region"/></region>
      <status><xsl:value-of select="status"/></status>
      <lead_score><xsl:value-of select="score"/></lead_score>
    </lead>
  </xsl:template>
</xsl:stylesheet>
